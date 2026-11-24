"""LLM client tests. Provider adapters are exercised against the real SDKs with a mocked HTTP
transport (httpx2.MockTransport), so request construction and response parsing are verified
without network access or API charges."""

import json

import httpx2
import pytest
from pydantic import SecretStr

from docintel.config import Settings, get_api_key
from docintel.credentials import Credential
from docintel.llm_client import (
    AnthropicProvider,
    GeminiProvider,
    LLMAuthenticationError,
    LLMBudgetExceededError,
    LLMConfigurationError,
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


def test_factory_falls_back_to_offline_without_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "server-env-key-must-not-be-used-0000")
    status = create_provider(Settings(provider="openai"), allow_offline_fallback=True)
    assert status.is_fallback and "No OpenAI API key" in status.fallback_reason
    assert status.provider.is_offline


def test_factory_raises_without_key_when_fallback_disabled(monkeypatch):
    """Adapters never look up a key themselves, even when the server environment has one."""
    monkeypatch.setenv("OPENAI_API_KEY", "server-env-key-must-not-be-used-0000")
    with pytest.raises(LLMConfigurationError, match="No OpenAI API key"):
        create_provider(Settings(provider="openai"))
    with pytest.raises(LLMConfigurationError, match="No OpenAI API key"):
        OpenAIProvider("gpt-6-luna", Settings(provider="openai"))


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


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "project_spend_limit_exceeded"),
        (429, "organization_spend_limit_exceeded"),
        (429, "organization_usage_limit_exceeded"),
        (429, "credit_balance_exhausted"),
        (402, "credit_balance_exhausted"),
    ],
)
def test_openai_spend_and_credit_limits_stop_without_retry(status, code):
    """A hard spend limit or an empty balance is not a rate limit: one call, no retries."""
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx2.Response(
            status, json={"error": {"message": "Limit reached", "type": "requests", "code": code}}
        )

    with pytest.raises(LLMQuotaError) as err:
        openai_provider(handler).generate(request())
    assert calls["n"] == 1
    assert "spend limit" in err.value.user_message


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


# ------------------------------------------------------------------ bring your own key

SESSION_KEY = "user-session-key-for-tests-0001"
# What a careless server environment could hold. None of it may reach a session-key request.
SERVER_ENV = {
    "OPENAI_API_KEY": "server-env-key-must-not-be-used-0000",
    "OPENAI_ADMIN_KEY": "server-env-admin-key-must-not-be-used",
    "OPENAI_ORG_ID": "org-server-operator",
    "OPENAI_PROJECT_ID": "proj-server-operator",
    "OPENAI_BASE_URL": "https://operator-proxy.invalid/v1",
    "ANTHROPIC_API_KEY": "server-env-anthropic-key-00000000",
    "ANTHROPIC_AUTH_TOKEN": "server-env-anthropic-token-0000000",
    "ANTHROPIC_BASE_URL": "https://operator-proxy.invalid",
    "GEMINI_API_KEY": "server-env-gemini-key-000000000000",
    "GOOGLE_API_KEY": "server-env-google-key-000000000000",
    "GOOGLE_GENAI_USE_VERTEXAI": "true",
}
SERVER_VALUES = [v for k, v in SERVER_ENV.items() if k != "GOOGLE_GENAI_USE_VERTEXAI"]
ANTHROPIC_OK = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-5-5",
    "content": [{"type": "text", "text": json.dumps(VALID_QA)}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
}
GEMINI_OK = {
    "candidates": [
        {
            "content": {"parts": [{"text": json.dumps(VALID_QA)}], "role": "model"},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
}


def session_credential(provider: str) -> Credential:
    return Credential(provider, SecretStr(SESSION_KEY), "session")


def mock_http(handler):
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def recorder(response_json, status=200):
    seen: dict = {}

    def handler(req):
        seen.update(method=req.method, url=str(req.url), headers=dict(req.headers))
        return httpx2.Response(status, json=response_json)

    return seen, handler


@pytest.fixture
def server_env(monkeypatch):
    for name, value in SERVER_ENV.items():
        monkeypatch.setenv(name, value)


def assert_no_server_values(seen: dict) -> None:
    sent = f"{seen['url']} {seen['headers']}"
    assert not [value for value in SERVER_VALUES if value in sent]


def test_openai_session_key_client_ignores_the_server_environment(server_env):
    seen, handler = recorder(openai_response())
    provider = OpenAIProvider(
        "gpt-6-luna",
        Settings(provider="openai"),
        credential=session_credential("openai"),
        http_client=mock_http(handler),
    )
    provider.generate(request())
    headers = {k.lower(): v for k, v in seen["headers"].items()}
    assert seen["url"].startswith("https://api.openai.com/v1/")
    assert headers["authorization"] == f"Bearer {SESSION_KEY}"
    assert "openai-organization" not in headers and "openai-project" not in headers
    assert provider.client.admin_api_key is None
    assert_no_server_values(seen)


def test_anthropic_session_key_client_ignores_the_server_environment(server_env):
    pytest.importorskip("anthropic")
    seen, handler = recorder(ANTHROPIC_OK)
    AnthropicProvider(
        "claude-haiku-5-5",
        Settings(provider="anthropic"),
        credential=session_credential("anthropic"),
        http_client=mock_http(handler),
    ).generate(request())
    headers = {k.lower(): v for k, v in seen["headers"].items()}
    assert seen["url"].startswith("https://api.anthropic.com/v1/messages")
    # anthropic 2.x sends the key as "Authorization: Bearer"; older versions used x-api-key.
    carriers = sorted(name for name, value in headers.items() if SESSION_KEY in value)
    assert carriers in (["authorization"], ["x-api-key"])
    assert_no_server_values(seen)


def test_gemini_session_key_client_ignores_the_server_environment(server_env):
    pytest.importorskip("google.genai")
    seen, handler = recorder(GEMINI_OK)
    GeminiProvider(
        "gemini-3.1-flash-lite",
        Settings(provider="gemini"),
        credential=session_credential("gemini"),
        http_client=mock_http(handler),
    ).generate(request())
    headers = {k.lower(): v for k, v in seen["headers"].items()}
    assert "generativelanguage.googleapis.com" in seen["url"]  # not Vertex AI
    assert headers.get("x-goog-api-key") == SESSION_KEY or f"key={SESSION_KEY}" in seen["url"]
    assert_no_server_values(seen)


@pytest.mark.parametrize(
    ("provider_class", "provider", "variable", "value"),
    [
        (OpenAIProvider, "openai", "OPENAI_CUSTOM_HEADERS", "X-Operator: yes"),
        (OpenAIProvider, "openai", "OPENAI_LOG", "debug"),
        (AnthropicProvider, "anthropic", "ANTHROPIC_CUSTOM_HEADERS", "X-Operator: yes"),
        (AnthropicProvider, "anthropic", "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE", "content"),
    ],
)
def test_session_keys_are_refused_while_unoverridable_sdk_settings_are_set(
    monkeypatch, provider_class, provider, variable, value
):
    monkeypatch.setenv(variable, value)
    calls = []
    with pytest.raises(LLMConfigurationError, match=variable) as err:
        provider_class(
            "model",
            Settings(provider=provider),
            credential=session_credential(provider),
            http_client=mock_http(calls.append),
        )
    assert calls == [] and SESSION_KEY not in str(err.value)


def test_the_owners_server_key_is_not_affected_by_the_session_key_refusal(monkeypatch):
    monkeypatch.setenv("OPENAI_LOG", "debug")
    server = Credential("openai", SecretStr(SESSION_KEY), "server")
    provider = OpenAIProvider("gpt-6-luna", Settings(provider="openai"), credential=server)
    assert provider.client.api_key == SESSION_KEY


def test_a_key_entered_for_one_provider_is_never_used_for_another():
    with pytest.raises(LLMConfigurationError, match="another provider"):
        AnthropicProvider(
            "claude-haiku-5-5",
            Settings(provider="anthropic"),
            credential=session_credential("openai"),
        )


def test_openai_key_check_only_reads_model_information():
    seen, handler = recorder({"id": "gpt-6-luna", "object": "model", "created": 1, "owned_by": "x"})
    provider = OpenAIProvider(
        "gpt-6-luna",
        Settings(provider="openai"),
        credential=session_credential("openai"),
        http_client=mock_http(handler),
    )
    provider.check_access()
    assert seen["method"] == "GET" and seen["url"].endswith("/v1/models/gpt-6-luna")
    assert provider.requests_made == 1


@pytest.mark.parametrize(
    ("status", "error", "expected", "fragment"),
    [
        (
            401,
            {"code": "invalid_api_key", "type": "invalid_request_error"},
            LLMAuthenticationError,
            "mistyped, revoked or expired",
        ),
        (
            404,
            {"code": "model_not_found", "type": "invalid_request_error"},
            LLMConfigurationError,
            "not available to your OpenAI account",
        ),
        (
            429,
            {"code": "insufficient_quota", "type": "insufficient_quota"},
            LLMQuotaError,
            "credit",
        ),
    ],
)
def test_key_check_errors_are_clear_and_never_echo_the_key(status, error, expected, fragment):
    # OpenAI echoes part of a rejected key in its error message.
    body = {
        "error": {
            **error,
            "message": f"Incorrect API key provided: {SESSION_KEY[:8]}...{SESSION_KEY[-6:]}",
        }
    }
    _, handler = recorder(body, status)
    provider = OpenAIProvider(
        "gpt-6-luna",
        Settings(provider="openai"),
        credential=session_credential("openai"),
        http_client=mock_http(handler),
    )
    with pytest.raises(expected) as err:
        provider.check_access()
    shown = f"{err.value} {err.value.user_message} {err.value!r}"
    assert fragment in err.value.user_message
    assert SESSION_KEY[:8] not in shown and SESSION_KEY[-6:] not in shown
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_anthropic_key_check_and_credit_balance_message():
    pytest.importorskip("anthropic")
    seen, ok = recorder(
        {
            "type": "model",
            "id": "claude-haiku-5-5",
            "display_name": "Haiku",
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    AnthropicProvider(
        "claude-haiku-5-5",
        Settings(provider="anthropic"),
        credential=session_credential("anthropic"),
        http_client=mock_http(ok),
    ).check_access()
    assert seen["method"] == "GET" and seen["url"].endswith("/v1/models/claude-haiku-5-5")
    low_credit = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API.",
        },
    }
    _, broke = recorder(low_credit, 400)
    with pytest.raises(LLMQuotaError, match="credit balance"):
        AnthropicProvider(
            "claude-haiku-5-5",
            Settings(provider="anthropic"),
            credential=session_credential("anthropic"),
            http_client=mock_http(broke),
        ).generate(request())


def test_gemini_key_check_and_invalid_key_message():
    pytest.importorskip("google.genai")
    seen, ok = recorder({"name": "models/gemini-3.1-flash-lite", "displayName": "Flash-Lite"})
    GeminiProvider(
        "gemini-3.1-flash-lite",
        Settings(provider="gemini"),
        credential=session_credential("gemini"),
        http_client=mock_http(ok),
    ).check_access()
    assert seen["method"] == "GET" and "models/gemini-3.1-flash-lite" in seen["url"]
    invalid = {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}
            ],
        }
    }
    _, rejected = recorder(invalid, 400)
    with pytest.raises(LLMAuthenticationError, match="rejected the API key"):
        GeminiProvider(
            "gemini-3.1-flash-lite",
            Settings(provider="gemini"),
            credential=session_credential("gemini"),
            http_client=mock_http(rejected),
        ).check_access()


def test_offline_provider_has_no_key_to_check():
    with pytest.raises(LLMConfigurationError, match="does not use an API key"):
        ExtractiveOfflineProvider(Settings(provider="mock")).check_access()
