"""LLM client tests. Provider adapters are exercised against the real SDKs with a mocked HTTP
transport (httpx2.MockTransport), so request construction and response parsing are verified
without network access or API charges."""

import json

import httpx2
import pytest

from docintel.config import Settings, get_api_key
from docintel.llm_client import (
    AnthropicProvider,
    GeminiProvider,
    LLMAuthenticationError,
    LLMBudgetExceededError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMResponseFormatError,
    LLMTimeoutError,
    OpenAIProvider,
    ScriptedProvider,
    StructuredRequest,
    create_provider,
)
from docintel.model_catalog import estimate_cost_usd, get_model_info
from docintel.models import QAOutput
from docintel.offline_provider import ExtractiveOfflineProvider
from tests.conftest import passage

VALID_QA = {
    "status": "answered",
    "answer": "The fee is $4,500.00 [S1].",
    "claims": [
        {
            "statement": "The monthly fee is $4,500.00.",
            "claim_type": "fact",
            "citations": [{"source_id": "S1", "quote": "monthly service fee of $4,500.00"}],
        }
    ],
    "conflicts": [],
    "missing_information": [],
    "confidence": "high",
}


def request(**context):
    return StructuredRequest("qa", "SYSTEM PROMPT", "USER PROMPT", QAOutput, context=context)


class SleepRecorder:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ------------------------------------------------------------------ shared retry / budget logic


def test_offline_provider_is_deterministic():
    ctx = {
        "question": "What is the monthly service fee?",
        "sources": [
            passage("S1", "The monthly service fee is $4,500.00. Invoices are due in 30 days.")
        ],
    }
    provider = ExtractiveOfflineProvider()
    first, second = provider.generate(request(**ctx)), provider.generate(request(**ctx))
    assert first.output == second.output
    assert (
        first.output.status == "answered" and first.output.claims[0].citations[0].source_id == "S1"
    )
    assert first.stats.cost_usd == 0.0 and first.stats.usage.estimated


def test_offline_provider_abstains_when_nothing_matches():
    ctx = {
        "question": "Which tree species were recommended?",
        "sources": [passage("S1", "The fee is $10.")],
    }
    out = ExtractiveOfflineProvider().generate(request(**ctx)).output
    assert out.status == "insufficient_evidence" and out.claims == []


def test_retries_rate_limit_then_succeeds():
    sleep = SleepRecorder()
    provider = ScriptedProvider(
        [LLMRateLimitError("slow down", retry_after=3.0), VALID_QA],
        Settings(provider="mock", max_retries=2),
        sleep=sleep,
    )
    result = provider.generate(request())
    assert result.stats.attempts == 2 and result.output.status == "answered"
    assert len(sleep.calls) == 1 and sleep.calls[0] >= 3.0


def test_backoff_is_capped():
    provider = ScriptedProvider([], Settings(provider="mock", retry_backoff_max_s=5.0))
    assert provider._backoff_delay(attempt=6, retry_after=120.0) == 5.0


def test_retries_are_bounded():
    sleep = SleepRecorder()
    errors = [LLMTimeoutError("timeout") for _ in range(10)]
    provider = ScriptedProvider(errors, Settings(provider="mock", max_retries=2), sleep=sleep)
    with pytest.raises(LLMTimeoutError):
        provider.generate(request())
    assert provider.requests_made == 3 and len(sleep.calls) == 2


def test_authentication_errors_are_not_retried():
    provider = ScriptedProvider(
        [LLMAuthenticationError("bad key"), VALID_QA], sleep=SleepRecorder()
    )
    with pytest.raises(LLMAuthenticationError):
        provider.generate(request())
    assert provider.requests_made == 1


def test_invalid_output_is_retried_once_then_raised():
    provider = ScriptedProvider(["not json", '{"status": "answered"}', VALID_QA])
    with pytest.raises(LLMResponseFormatError):
        provider.generate(request())
    assert provider.requests_made == 2


def test_invalid_output_recovers_on_second_attempt():
    provider = ScriptedProvider(["{broken", VALID_QA])
    assert provider.generate(request()).stats.attempts == 2


def test_request_budget_is_enforced():
    provider = ScriptedProvider(
        [VALID_QA, VALID_QA], Settings(provider="mock", max_requests_per_session=1)
    )
    provider.generate(request())
    with pytest.raises(LLMBudgetExceededError):
        provider.generate(request())


def test_cost_estimates_use_catalog_prices():
    assert estimate_cost_usd("gpt-6-luna", 1_000_000, 1_000_000) == pytest.approx(0.10 + 0.50)
    assert estimate_cost_usd(
        "gpt-6-luna", 1_000_000, 0, cached_input_tokens=1_000_000
    ) == pytest.approx(0.01)
    # Haiku 5.5 bills prompts over 100k tokens at a higher rate.
    assert estimate_cost_usd("claude-haiku-5-5", 200_000, 0) == pytest.approx(0.10)
    assert estimate_cost_usd("not-a-model", 10, 10) is None
    assert get_model_info("gemini-3.1-flash-lite").provider == "gemini"


# ------------------------------------------------------------------ factory and keys


def test_factory_falls_back_to_offline_without_key():
    status = create_provider(Settings(provider="openai"), allow_offline_fallback=True)
    assert status.is_fallback and "OPENAI_API_KEY" in status.fallback_reason
    assert status.provider.is_offline


def test_factory_raises_without_key_when_fallback_disabled():
    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        create_provider(Settings(provider="openai"))


def test_api_keys_are_secret_and_never_in_settings():
    key = get_api_key("openai", env={"OPENAI_API_KEY": "sk-test-abcdef123456"})
    assert key is not None and "sk-test" not in repr(key) and "sk-test" not in str(key)
    assert "api_key" not in Settings.model_fields
    assert get_api_key("gemini", env={"GOOGLE_API_KEY": "g-key"}).get_secret_value() == "g-key"


# ------------------------------------------------------------------ OpenAI adapter contract


def openai_response(payload=None, status="completed"):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-6-luna",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(payload or VALID_QA),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 1200,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens": 300,
            "output_tokens_details": {"reasoning_tokens": 64},
            "total_tokens": 1500,
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


def openai_provider(handler, settings=None, sleep=None):
    import openai

    client = openai.OpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIProvider(
        "gpt-6-luna",
        settings or Settings(provider="openai"),
        client=client,
        sleep=sleep or SleepRecorder(),
    )


def test_openai_request_contract_and_usage_mapping():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx2.Response(200, json=openai_response())

    result = openai_provider(handler).generate(request())
    body = seen["body"]
    assert seen["url"].endswith("/responses")
    assert body["model"] == "gpt-6-luna" and body["store"] is False
    assert body["instructions"] == "SYSTEM PROMPT"
    assert body["input"] == [{"role": "user", "content": "USER PROMPT"}]
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert body["reasoning"] == {"effort": "low"} and "temperature" not in body
    assert result.output.claims[0].citations[0].quote == "monthly service fee of $4,500.00"
    usage = result.stats.usage
    assert (
        usage.input_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.cached_input_tokens,
    ) == (1200, 300, 64, 200)
    assert result.stats.cost_usd == pytest.approx((1000 * 0.10 + 200 * 0.01 + 300 * 0.50) / 1e6)


def test_openai_rate_limit_is_retried_with_retry_after():
    calls = {"n": 0}
    sleep = SleepRecorder()

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(
                429,
                headers={"retry-after": "2"},
                json={
                    "error": {
                        "message": "Rate limit",
                        "type": "requests",
                        "code": "rate_limit_exceeded",
                    }
                },
            )
        return httpx2.Response(200, json=openai_response())

    result = openai_provider(handler, sleep=sleep).generate(request())
    assert calls["n"] == 2 and result.stats.attempts == 2 and sleep.calls[0] >= 2.0


def test_openai_insufficient_quota_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx2.Response(
            429,
            json={
                "error": {
                    "message": "You exceeded your current quota",
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                }
            },
        )

    with pytest.raises(LLMQuotaError):
        openai_provider(handler).generate(request())
    assert calls["n"] == 1


def test_openai_authentication_error_is_mapped():
    def handler(req):
        return httpx2.Response(
            401, json={"error": {"message": "Incorrect API key", "code": "invalid_api_key"}}
        )

    with pytest.raises(LLMAuthenticationError) as err:
        openai_provider(handler).generate(request())
    assert "sk-test" not in err.value.user_message


def test_openai_incomplete_response_is_a_format_error():
    def handler(req):
        return httpx2.Response(
            200,
            json={
                **openai_response(),
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        )

    with pytest.raises(LLMResponseFormatError):
        openai_provider(handler).generate(request())


def test_openai_optional_temperature_is_sent_when_configured():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx2.Response(200, json=openai_response())

    settings = Settings(provider="openai", temperature=0.0, reasoning_effort=None)
    openai_provider(handler, settings=settings).generate(request())
    assert seen["body"]["temperature"] == 0.0 and "reasoning" not in seen["body"]


# ------------------------------------------------------------------ Anthropic adapter contract


def test_anthropic_request_contract():
    anthropic = pytest.importorskip("anthropic")

    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [{"type": "text", "text": json.dumps(VALID_QA)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        )

    client = anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    result = AnthropicProvider(
        "claude-haiku-5-5", Settings(provider="anthropic"), client=client
    ).generate(request())
    body = seen["body"]
    assert seen["url"].endswith("/v1/messages")
    assert (
        body["system"] == "SYSTEM PROMPT"
        and body["output_config"]["format"]["type"] == "json_schema"
    )
    assert "temperature" not in body
    assert result.output.status == "answered"
    assert result.stats.cost_usd == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)


def test_anthropic_max_tokens_stop_is_a_format_error():
    anthropic = pytest.importorskip("anthropic")

    def handler(req):
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [{"type": "text", "text": '{"status": "answ'}],
                "stop_reason": "max_tokens",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    client = anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(LLMResponseFormatError):
        AnthropicProvider(
            "claude-haiku-5-5", Settings(provider="anthropic"), client=client
        ).generate(request())


# ------------------------------------------------------------------ Gemini adapter contract


def test_gemini_request_contract():
    genai = pytest.importorskip("google.genai")
    types = pytest.importorskip("google.genai.types")

    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": json.dumps(VALID_QA)}], "role": "model"},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1000,
                    "candidatesTokenCount": 200,
                    "thoughtsTokenCount": 50,
                },
            },
        )

    client = genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))
        ),
    )
    result = GeminiProvider(
        "gemini-3.1-flash-lite", Settings(provider="gemini"), client=client
    ).generate(request())
    body = seen["body"]
    assert "gemini-3.1-flash-lite:generateContent" in seen["url"]
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json" and "responseJsonSchema" in config
    assert body["systemInstruction"]["parts"][0]["text"] == "SYSTEM PROMPT"
    assert (
        result.stats.usage.output_tokens == 250
    )  # candidates + thinking tokens are both billed as output
    assert result.output.status == "answered"


def test_gemini_rate_limit_is_mapped_and_retried():
    genai = pytest.importorskip("google.genai")
    types = pytest.importorskip("google.genai.types")

    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx2.Response(
            429,
            json={
                "error": {
                    "code": 429,
                    "message": "Resource exhausted",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    client = genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))
        ),
    )
    provider = GeminiProvider(
        "gemini-3.1-flash-lite",
        Settings(provider="gemini", max_retries=1),
        client=client,
        sleep=SleepRecorder(),
    )
    with pytest.raises(LLMRateLimitError):
        provider.generate(request())
    assert calls["n"] == 2
