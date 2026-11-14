"""Provider-agnostic LLM client for structured (JSON-schema) generation.

Every provider implements ``_call(request) -> (parsed_output, usage, raw_text)``. The shared
:meth:`LLMProvider.generate` adds the behaviour the application relies on:

* a per-session request budget (``max_requests_per_session``),
* bounded retries with exponential backoff and ``Retry-After`` support for rate limits,
  timeouts, connection problems and server errors (never for authentication or bad requests),
* one extra attempt when the model returns output that fails schema validation,
* token usage, latency and cost accounting.

Model identifiers come from configuration (``Settings.resolved_model``); no workflow module
names a model. SDK clients are created with their own retries disabled so retry behaviour is
explicit, testable and bounded in one place.
"""

from __future__ import annotations

import json
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from docintel.config import Settings, get_api_key
from docintel.model_catalog import estimate_cost_usd
from docintel.security import get_logger

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- errors


class LLMError(Exception):
    """Base class. ``user_message`` is safe to show in the UI."""

    kind = "provider_error"
    retryable = False

    def __init__(self, user_message: str, *, detail: str = "", retry_after: float | None = None):
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.retry_after = retry_after


class LLMConfigurationError(LLMError):
    kind = "configuration"


class LLMAuthenticationError(LLMError):
    kind = "authentication"


class LLMQuotaError(LLMError):
    kind = "quota"


class LLMBudgetExceededError(LLMError):
    kind = "request_budget"


class LLMBadRequestError(LLMError):
    kind = "bad_request"


class LLMRefusalError(LLMError):
    kind = "refusal"


class LLMRateLimitError(LLMError):
    kind = "rate_limit"
    retryable = True


class LLMTimeoutError(LLMError):
    kind = "timeout"
    retryable = True


class LLMConnectionError(LLMError):
    kind = "connection"
    retryable = True


class LLMServerError(LLMError):
    kind = "server"
    retryable = True


class LLMResponseFormatError(LLMError):
    """The model's output could not be parsed/validated against the requested schema."""

    kind = "invalid_output"


# --------------------------------------------------------------------------- request / result


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0  # includes reasoning/thinking tokens where the provider bills them
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated: bool = False  # True when counted heuristically (offline provider)

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            estimated=self.estimated or other.estimated,
        )


@dataclass
class CallStats:
    provider: str
    model: str
    usage: TokenUsage
    latency_s: float
    attempts: int
    cost_usd: float | None

    @staticmethod
    def combine(stats: Sequence[CallStats]) -> CallStats | None:
        if not stats:
            return None
        usage = TokenUsage()
        for s in stats:
            usage = usage + s.usage
        costs = [s.cost_usd for s in stats]
        return CallStats(
            provider=stats[0].provider,
            model=stats[0].model,
            usage=usage,
            latency_s=sum(s.latency_s for s in stats),
            attempts=sum(s.attempts for s in stats),
            cost_usd=None
            if any(c is None for c in costs)
            else sum(c for c in costs if c is not None),
        )


@dataclass
class StructuredRequest:
    task: str  # qa | summary_map | summary_reduce | extraction | comparison | judge
    system: str
    user: str
    response_model: type[BaseModel]
    max_output_tokens: int | None = None
    # Structured inputs (sources, question, ...) for the offline provider and diagnostics.
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredResult(Generic[T]):
    output: T
    stats: CallStats
    raw_text: str | None = None


# --------------------------------------------------------------------------- base provider


class LLMProvider(ABC):
    provider_name = "base"
    is_offline = False

    def __init__(
        self, model: str, settings: Settings, *, sleep: Callable[[float], None] = time.sleep
    ):
        self.model = model
        self.settings = settings
        self._sleep = sleep
        self.requests_made = 0

    @property
    def label(self) -> str:
        return f"{self.provider_name}:{self.model}"

    def generate(self, request: StructuredRequest) -> StructuredResult:
        attempts = 0
        format_retry_used = False
        started = time.perf_counter()
        while True:
            if self.requests_made >= self.settings.max_requests_per_session:
                raise LLMBudgetExceededError(
                    "This session reached its request limit "
                    f"({self.settings.max_requests_per_session} model calls). Clear the session or "
                    "raise DOCINTEL_MAX_REQUESTS_PER_SESSION."
                )
            attempts += 1
            self.requests_made += 1
            try:
                output, usage, raw = self._call(request)
                break
            except LLMResponseFormatError:
                log.warning(
                    "invalid_output task=%s model=%s attempt=%d", request.task, self.model, attempts
                )
                if format_retry_used:
                    raise
                format_retry_used = True
            except LLMError as err:
                log.warning(
                    "llm_error kind=%s task=%s model=%s attempt=%d",
                    err.kind,
                    request.task,
                    self.model,
                    attempts,
                )
                if not err.retryable or attempts > self.settings.max_retries:
                    raise
                self._sleep(self._backoff_delay(attempts, err.retry_after))
        latency = time.perf_counter() - started
        cost = (
            0.0
            if self.is_offline
            else estimate_cost_usd(
                self.model, usage.input_tokens, usage.output_tokens, usage.cached_input_tokens
            )
        )
        stats = CallStats(self.provider_name, self.model, usage, latency, attempts, cost)
        log.info(
            "llm_call task=%s provider=%s model=%s attempts=%d latency_s=%.2f in_tok=%d out_tok=%d",
            request.task,
            self.provider_name,
            self.model,
            attempts,
            latency,
            usage.input_tokens,
            usage.output_tokens,
        )
        return StructuredResult(output=output, stats=stats, raw_text=raw)

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        base = self.settings.retry_backoff_base_s * (2 ** (attempt - 1))
        delay = base + random.uniform(0, base * 0.25)
        if retry_after is not None:
            delay = max(delay, retry_after)
        return min(delay, self.settings.retry_backoff_max_s)

    def _max_tokens(self, request: StructuredRequest) -> int:
        return request.max_output_tokens or self.settings.max_output_tokens

    @staticmethod
    def _validate_json(response_model: type[T], raw: str | None) -> T:
        if not raw:
            raise LLMResponseFormatError("The model returned an empty response. Please try again.")
        try:
            return response_model.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError, ValueError):
            raise LLMResponseFormatError(
                "The model returned output that did not match the expected format. Please try again."
            ) from None

    @abstractmethod
    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        """Perform one API call and return (validated output, usage, raw text)."""


def _retry_after_seconds(response: Any) -> float | None:
    try:
        value = response.headers.get("retry-after") if response is not None else None
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- OpenAI


class OpenAIProvider(LLMProvider):
    """OpenAI Responses API with Structured Outputs (strict JSON schema via ``responses.parse``).

    ``store=False`` is always sent: the Responses API otherwise stores responses by default.
    """

    provider_name = "openai"

    def __init__(self, model: str, settings: Settings, *, client: Any | None = None, **kwargs: Any):
        super().__init__(model, settings, **kwargs)
        if client is None:
            key = get_api_key("openai")
            if key is None:
                raise LLMConfigurationError("OPENAI_API_KEY is not set. Add it to your .env file.")
            import openai

            client = openai.OpenAI(
                api_key=key.get_secret_value(), timeout=settings.request_timeout_s, max_retries=0
            )
        self.client = client

    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        import openai

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": request.system,
            "input": [{"role": "user", "content": request.user}],
            "text_format": request.response_model,
            "max_output_tokens": self._max_tokens(request),
            "store": False,
        }
        if self.settings.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.settings.reasoning_effort}
        if self.settings.temperature is not None:
            kwargs["temperature"] = self.settings.temperature
        try:
            response = self.client.responses.parse(**kwargs)
        except openai.AuthenticationError:
            raise LLMAuthenticationError(
                "OpenAI rejected the API key. Check OPENAI_API_KEY."
            ) from None
        except openai.PermissionDeniedError:
            raise LLMAuthenticationError(
                "Your OpenAI project is not permitted to use this model or endpoint."
            ) from None
        except openai.RateLimitError as exc:
            if "insufficient_quota" in str(getattr(exc, "body", "") or exc):
                raise LLMQuotaError(
                    "The OpenAI account has no remaining quota or billing is not set up."
                ) from None
            raise LLMRateLimitError(
                "OpenAI rate limit reached. Please wait a moment and retry.",
                retry_after=_retry_after_seconds(getattr(exc, "response", None)),
            ) from None
        except openai.APITimeoutError:
            raise LLMTimeoutError("The OpenAI request timed out. Please retry.") from None
        except openai.APIConnectionError:
            raise LLMConnectionError(
                "Could not reach the OpenAI API. Check your network."
            ) from None
        except openai.NotFoundError:
            raise LLMConfigurationError(
                f"Model '{self.model}' was not found or is not available to your OpenAI account."
            ) from None
        except openai.BadRequestError as exc:
            log.warning("openai_bad_request code=%s", getattr(exc, "code", None))
            raise LLMBadRequestError(
                "OpenAI rejected the request (HTTP 400). The selected model may not support one of "
                "the configured options (e.g. temperature or reasoning effort)."
            ) from None
        except openai.LengthFinishReasonError:
            raise LLMResponseFormatError(
                "The response was cut off before it was complete."
            ) from None
        except openai.APIStatusError as exc:
            if getattr(exc, "status_code", 0) >= 500:
                raise LLMServerError("OpenAI returned a server error. Please retry.") from None
            raise LLMBadRequestError(f"OpenAI returned HTTP {exc.status_code}.") from None
        except (ValidationError, json.JSONDecodeError):
            raise LLMResponseFormatError(
                "The model returned output that did not match the schema."
            ) from None

        if getattr(response, "status", None) == "incomplete":
            raise LLMResponseFormatError(
                "The response was incomplete (output token limit reached). Try a narrower request."
            )
        parsed = getattr(response, "output_parsed", None)
        raw = getattr(response, "output_text", None)
        if parsed is None:
            for item in getattr(response, "output", []) or []:
                for content in getattr(item, "content", []) or []:
                    if getattr(content, "type", "") == "refusal":
                        raise LLMRefusalError("The model declined to answer this request.")
            parsed = self._validate_json(request.response_model, raw)
        usage = getattr(response, "usage", None)
        out_details = getattr(usage, "output_tokens_details", None)
        in_details = getattr(usage, "input_tokens_details", None)
        token_usage = TokenUsage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            reasoning_tokens=getattr(out_details, "reasoning_tokens", 0) or 0,
            cached_input_tokens=getattr(in_details, "cached_tokens", 0) or 0,
        )
        return parsed, token_usage, raw


# --------------------------------------------------------------------------- Anthropic


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API with native structured outputs (``output_config.format``).

    Uses the SDK helper ``messages.parse(output_format=Model)``, which converts the Pydantic
    model to a JSON schema and validates the response. Temperature is not sent: the current
    Messages API surface (SDK 2.x) does not accept sampling parameters for these models.
    """

    provider_name = "anthropic"

    def __init__(self, model: str, settings: Settings, *, client: Any | None = None, **kwargs: Any):
        super().__init__(model, settings, **kwargs)
        if client is None:
            key = get_api_key("anthropic")
            if key is None:
                raise LLMConfigurationError(
                    "ANTHROPIC_API_KEY is not set. Add it to your .env file."
                )
            try:
                import anthropic
            except ImportError:
                raise LLMConfigurationError(
                    "The 'anthropic' package is not installed. Run: pip install -e '.[anthropic]'"
                ) from None
            client = anthropic.Anthropic(
                api_key=key.get_secret_value(), timeout=settings.request_timeout_s, max_retries=0
            )
        self.client = client

    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        import anthropic

        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=self._max_tokens(request),
                system=request.system,
                messages=[{"role": "user", "content": request.user}],
                output_format=request.response_model,
            )
        except anthropic.AuthenticationError:
            raise LLMAuthenticationError(
                "Anthropic rejected the API key. Check ANTHROPIC_API_KEY."
            ) from None
        except anthropic.PermissionDeniedError:
            raise LLMAuthenticationError(
                "Your Anthropic key is not permitted to use this model."
            ) from None
        except anthropic.RateLimitError as exc:
            raise LLMRateLimitError(
                "Anthropic rate limit reached. Please wait a moment and retry.",
                retry_after=_retry_after_seconds(getattr(exc, "response", None)),
            ) from None
        except anthropic.APITimeoutError:
            raise LLMTimeoutError("The Anthropic request timed out. Please retry.") from None
        except anthropic.APIConnectionError:
            raise LLMConnectionError(
                "Could not reach the Anthropic API. Check your network."
            ) from None
        except anthropic.NotFoundError:
            raise LLMConfigurationError(
                f"Model '{self.model}' was not found on the Anthropic API."
            ) from None
        except anthropic.BadRequestError:
            raise LLMBadRequestError("Anthropic rejected the request (HTTP 400).") from None
        except anthropic.InternalServerError:  # includes 529 overloaded
            raise LLMServerError(
                "Anthropic returned a server/overloaded error. Please retry."
            ) from None
        except anthropic.APIStatusError as exc:
            raise LLMBadRequestError(f"Anthropic returned HTTP {exc.status_code}.") from None
        except (ValidationError, json.JSONDecodeError, ValueError):
            raise LLMResponseFormatError(
                "The model returned output that did not match the schema."
            ) from None

        raw = (
            "".join(
                getattr(block, "text", "")
                for block in (response.content or [])
                if getattr(block, "type", "") == "text"
            )
            or None
        )
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise LLMRefusalError("The model declined to answer this request.")
        if stop_reason == "max_tokens":
            raise LLMResponseFormatError(
                "The response was cut off (max_tokens reached). Try a narrower request."
            )
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            parsed = self._validate_json(request.response_model, raw)
        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=(usage.input_tokens or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=usage.output_tokens or 0,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )
        return parsed, token_usage, raw


# --------------------------------------------------------------------------- Google Gemini


class GeminiProvider(LLMProvider):
    """Google Gemini API (google-genai SDK) with ``response_json_schema`` structured output."""

    provider_name = "gemini"

    def __init__(self, model: str, settings: Settings, *, client: Any | None = None, **kwargs: Any):
        super().__init__(model, settings, **kwargs)
        if client is None:
            key = get_api_key("gemini")
            if key is None:
                raise LLMConfigurationError("GEMINI_API_KEY is not set. Add it to your .env file.")
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise LLMConfigurationError(
                    "The 'google-genai' package is not installed. Run: pip install -e '.[gemini]'"
                ) from None
            client = genai.Client(
                api_key=key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(settings.request_timeout_s * 1000)),
            )
        self.client = client

    def _thinking_level(self) -> str | None:
        effort = (self.settings.reasoning_effort or "").lower()
        if not effort:
            return None
        return {"none": "minimal", "minimal": "minimal", "low": "low", "medium": "medium"}.get(
            effort, "high"
        )

    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        import httpx2  # HTTP library used by google-genai 3.x (and the OpenAI/Anthropic SDKs)
        from google.genai import errors, types

        config_kwargs: dict[str, Any] = {
            "system_instruction": request.system,
            "response_mime_type": "application/json",
            "response_json_schema": request.response_model.model_json_schema(),
            "max_output_tokens": self._max_tokens(request),
        }
        level = self._thinking_level()
        if level:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        if self.settings.temperature is not None:
            config_kwargs["temperature"] = self.settings.temperature
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=request.user,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except errors.ClientError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                raise LLMRateLimitError(
                    "Gemini rate limit or quota reached. Please retry later."
                ) from None
            if code in (401, 403):
                raise LLMAuthenticationError(
                    "Gemini rejected the API key. Check GEMINI_API_KEY."
                ) from None
            if code == 404:
                raise LLMConfigurationError(
                    f"Model '{self.model}' was not found on the Gemini API."
                ) from None
            raise LLMBadRequestError(f"Gemini rejected the request (HTTP {code}).") from None
        except errors.ServerError:
            raise LLMServerError("Gemini returned a server error. Please retry.") from None
        except httpx2.TimeoutException:
            raise LLMTimeoutError("The Gemini request timed out. Please retry.") from None
        except httpx2.TransportError:
            raise LLMConnectionError(
                "Could not reach the Gemini API. Check your network."
            ) from None

        candidates = getattr(response, "candidates", None) or []
        finish = str(getattr(candidates[0], "finish_reason", "")) if candidates else ""
        if "MAX_TOKENS" in finish:
            raise LLMResponseFormatError("The response was cut off (output token limit reached).")
        if not candidates or any(
            k in finish for k in ("SAFETY", "PROHIBITED", "BLOCKLIST", "RECITATION")
        ):
            raise LLMRefusalError(
                "Gemini did not return an answer for this request (blocked or empty)."
            )
        raw = response.text
        parsed = self._validate_json(request.response_model, raw)
        meta = getattr(response, "usage_metadata", None)
        thoughts = getattr(meta, "thoughts_token_count", 0) or 0
        token_usage = TokenUsage(
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=(getattr(meta, "candidates_token_count", 0) or 0) + thoughts,
            reasoning_tokens=thoughts,
            cached_input_tokens=getattr(meta, "cached_content_token_count", 0) or 0,
        )
        return parsed, token_usage, raw


# --------------------------------------------------------------------------- scripted (tests)


class ScriptedProvider(LLMProvider):
    """Returns pre-defined outputs in order. Used by tests and validator experiments.

    Each script item may be a Pydantic model, a dict, a raw JSON string, or an exception
    instance (which is raised).
    """

    provider_name = "scripted"
    is_offline = True

    def __init__(self, outputs: Sequence[Any], settings: Settings | None = None, **kwargs: Any):
        super().__init__("scripted", settings or Settings(provider="mock"), **kwargs)
        self._outputs = list(outputs)
        self.requests: list[StructuredRequest] = []

    def _call(self, request: StructuredRequest) -> tuple[BaseModel, TokenUsage, str | None]:
        self.requests.append(request)
        if not self._outputs:
            raise LLMResponseFormatError("ScriptedProvider has no more outputs.")
        item = self._outputs.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, BaseModel):
            raw = item.model_dump_json()
        elif isinstance(item, dict):
            raw = json.dumps(item)
        else:
            raw = str(item)
        parsed = self._validate_json(request.response_model, raw)
        usage = TokenUsage(len(request.system + request.user) // 4, len(raw) // 4, estimated=True)
        return parsed, usage, raw


# --------------------------------------------------------------------------- factory


@dataclass
class ProviderStatus:
    provider: LLMProvider
    requested_provider: str
    fallback_reason: str | None = None

    @property
    def is_fallback(self) -> bool:
        return self.fallback_reason is not None


def create_provider(settings: Settings, *, allow_offline_fallback: bool = False) -> ProviderStatus:
    """Instantiate the configured provider.

    With ``allow_offline_fallback`` (used by the UI), a missing key or SDK falls back to the
    offline extractive provider and the reason is reported so the UI can say so prominently.
    """
    from docintel.offline_provider import ExtractiveOfflineProvider

    model = settings.resolved_model
    classes: dict[str, type[LLMProvider]] = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
    }
    if settings.provider == "mock":
        return ProviderStatus(ExtractiveOfflineProvider(settings), "mock")
    try:
        provider = classes[settings.provider](model, settings)
        return ProviderStatus(provider, settings.provider)
    except LLMConfigurationError as exc:
        if not allow_offline_fallback:
            raise
        return ProviderStatus(
            ExtractiveOfflineProvider(settings), settings.provider, exc.user_message
        )
