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

Adapters never look up API keys themselves: the caller passes a :class:`Credential`. A key typed
in a browser session gets a "sealed" SDK client. Its key and endpoint are passed explicitly, and
settings the SDK copied from the server environment (organization and project IDs, admin keys,
the Vertex AI switch) are cleared. If the server sets variables the SDK would still apply to
every request (extra headers, debug logging, content telemetry), the key is refused instead.
"""

from __future__ import annotations

import json
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from docintel.config import Settings
from docintel.credentials import PROVIDER_NAMES, Credential, unsafe_sdk_environment
from docintel.model_catalog import estimate_cost_usd
from docintel.security import get_logger

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)

OPENAI_API_BASE = "https://api.openai.com/v1"
ANTHROPIC_API_BASE = "https://api.anthropic.com"


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

    def _count_request(self) -> None:
        if self.requests_made >= self.settings.max_requests_per_session:
            raise LLMBudgetExceededError(
                "This session reached its request limit "
                f"({self.settings.max_requests_per_session} model calls). Clear the session or "
                "raise DOCINTEL_MAX_REQUESTS_PER_SESSION."
            )
        self.requests_made += 1

    def check_access(self) -> None:
        """Confirm the key works and can use this model, with one model-information request.

        No text is generated, so no tokens are used; the request does count toward the
        provider's rate limits and this session's request budget. Raises :class:`LLMError`.
        """
        raise LLMConfigurationError("This provider does not use an API key.")

    def generate(self, request: StructuredRequest) -> StructuredResult:
        attempts = 0
        format_retry_used = False
        started = time.perf_counter()
        while True:
            self._count_request()
            attempts += 1
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


def _require_credential(credential: Credential | None, provider: str) -> Credential:
    """Adapters only use a key handed to them; they never fall back to the environment."""
    name = PROVIDER_NAMES[provider]
    if credential is None:
        raise LLMConfigurationError(f"No {name} API key is available for this session.")
    if credential.provider != provider:
        raise LLMConfigurationError(f"That API key was entered for another provider, not {name}.")
    if credential.is_session_key:
        unsafe = unsafe_sdk_environment(provider)
        if unsafe:
            raise LLMConfigurationError(
                f"This server sets {', '.join(unsafe)}, which the {name} SDK would apply to "
                "requests made with your key, so keys entered in the browser can't be used here. "
                "The operator must remove the setting; nothing was sent."
            )
    return credential


def _rejected_key_message(name: str) -> str:
    return f"{name} rejected the API key. It may be mistyped, revoked or expired."


def _retry_after_seconds(response: Any) -> float | None:
    try:
        value = response.headers.get("retry-after") if response is not None else None
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- OpenAI

# Error codes OpenAI returns when a billing control stops a request (HTTP 429 for spend limits).
# Retrying cannot help, so they map to LLMQuotaError, which is never retried. Source:
# https://developers.openai.com/api/docs/guides/spend-limits (checked 2026-11-14);
# insufficient_quota is the older code for an exhausted balance.
_OPENAI_BILLING_CODES = (
    "insufficient_quota",
    "credit_balance_exhausted",
    "project_spend_limit_exceeded",
    "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
)
_OPENAI_BILLING_MESSAGE = (
    "OpenAI stopped the request because a spend limit, usage limit or the prepaid credit "
    "balance was reached. Check Limits and Billing in the OpenAI dashboard."
)


def _is_openai_billing_block(exc: Exception) -> bool:
    detail = f"{getattr(exc, 'code', '') or ''} {getattr(exc, 'body', '') or exc}"
    return any(code in detail for code in _OPENAI_BILLING_CODES)


# Anthropic reports billing blocks as errors whose message mentions the credit balance or usage
# limits (an HTTP 400 for an empty credit balance), not with dedicated codes. The phrases are a
# heuristic: an unmatched billing error is still reported, as a rejected request.
_ANTHROPIC_BILLING_PHRASES = ("credit balance", "usage limit", "spend limit")
_ANTHROPIC_BILLING_MESSAGE = (
    "Anthropic stopped the request because the account's credit balance is too low or a usage "
    "limit was reached. Check Billing and Limits in the Claude Console."
)


def _is_anthropic_billing_block(exc: Exception) -> bool:
    detail = f"{getattr(exc, 'body', '') or ''} {getattr(exc, 'message', '') or ''}".lower()
    return any(phrase in detail for phrase in _ANTHROPIC_BILLING_PHRASES)


_GEMINI_KEY_PROBLEM = re.compile(r"API_KEY_INVALID|API key not valid|API key expired", re.I)


class OpenAIProvider(LLMProvider):
    """OpenAI Responses API with Structured Outputs (strict JSON schema via ``responses.parse``).

    ``store=False`` is always sent: the Responses API otherwise stores responses by default.
    """

    provider_name = "openai"

    def __init__(
        self,
        model: str,
        settings: Settings,
        *,
        credential: Credential | None = None,
        client: Any | None = None,
        http_client: Any | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, settings, **kwargs)
        if client is None:
            credential = _require_credential(credential, "openai")
            import openai

            sealed = credential.is_session_key
            client = openai.OpenAI(
                api_key=credential.secret.get_secret_value(),
                # A session key always goes to OpenAI itself, never to OPENAI_BASE_URL.
                base_url=OPENAI_API_BASE if sealed else None,
                timeout=settings.request_timeout_s,
                max_retries=0,
                http_client=http_client,
            )
            if sealed:
                # The SDK copies OPENAI_ORG_ID, OPENAI_PROJECT_ID and OPENAI_ADMIN_KEY from the
                # server environment. They belong to the server operator, not this user.
                client.organization = None
                client.project = None
                client.admin_api_key = None
        self.client = client

    def check_access(self) -> None:
        import openai

        self._count_request()
        try:
            self.client.models.retrieve(self.model)
        except openai.OpenAIError as exc:
            raise self._translate_error(exc) from None

    def _translate_error(self, exc: Exception) -> LLMError:
        import openai

        if isinstance(exc, openai.AuthenticationError):
            return LLMAuthenticationError(_rejected_key_message("OpenAI"))
        if isinstance(exc, openai.PermissionDeniedError):
            return LLMAuthenticationError(
                "Your OpenAI project is not permitted to use this model or endpoint."
            )
        if isinstance(exc, openai.RateLimitError):
            if _is_openai_billing_block(exc):
                return LLMQuotaError(_OPENAI_BILLING_MESSAGE)
            return LLMRateLimitError(
                "OpenAI rate limit reached. Please wait a moment and retry.",
                retry_after=_retry_after_seconds(getattr(exc, "response", None)),
            )
        if isinstance(exc, openai.APITimeoutError):
            return LLMTimeoutError("The OpenAI request timed out. Please retry.")
        if isinstance(exc, openai.APIConnectionError):
            return LLMConnectionError("Could not reach the OpenAI API. Check your network.")
        if isinstance(exc, openai.NotFoundError):
            return LLMConfigurationError(
                f"Model '{self.model}' was not found or is not available to your OpenAI account."
            )
        if isinstance(exc, openai.BadRequestError):
            log.warning("openai_bad_request code=%s", getattr(exc, "code", None))
            return LLMBadRequestError(
                "OpenAI rejected the request (HTTP 400). The selected model may not support one of "
                "the configured options (e.g. temperature or reasoning effort)."
            )
        if isinstance(exc, openai.APIStatusError):
            if getattr(exc, "status_code", 0) >= 500:
                return LLMServerError("OpenAI returned a server error. Please retry.")
            if _is_openai_billing_block(exc):
                return LLMQuotaError(_OPENAI_BILLING_MESSAGE)
            return LLMBadRequestError(f"OpenAI returned HTTP {exc.status_code}.")
        return LLMError("The OpenAI request failed.")

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
        except openai.LengthFinishReasonError:
            raise LLMResponseFormatError(
                "The response was cut off before it was complete."
            ) from None
        except (ValidationError, json.JSONDecodeError):
            raise LLMResponseFormatError(
                "The model returned output that did not match the schema."
            ) from None
        except openai.OpenAIError as exc:
            raise self._translate_error(exc) from None

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

    def __init__(
        self,
        model: str,
        settings: Settings,
        *,
        credential: Credential | None = None,
        client: Any | None = None,
        http_client: Any | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, settings, **kwargs)
        if client is None:
            credential = _require_credential(credential, "anthropic")
            try:
                import anthropic
            except ImportError:
                raise LLMConfigurationError(
                    "The 'anthropic' package is not installed. Run: pip install -e '.[anthropic]'"
                ) from None
            # An explicit api_key stops the SDK from reading ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN
            # or saved profiles; an explicit base_url keeps a session key away from
            # ANTHROPIC_BASE_URL.
            client = anthropic.Anthropic(
                api_key=credential.secret.get_secret_value(),
                base_url=ANTHROPIC_API_BASE if credential.is_session_key else None,
                timeout=settings.request_timeout_s,
                max_retries=0,
                http_client=http_client,
            )
        self.client = client

    def check_access(self) -> None:
        import anthropic

        self._count_request()
        try:
            self.client.models.retrieve(self.model)
        except anthropic.AnthropicError as exc:
            raise self._translate_error(exc) from None

    def _translate_error(self, exc: Exception) -> LLMError:
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            return LLMAuthenticationError(_rejected_key_message("Anthropic"))
        if isinstance(exc, anthropic.APIStatusError) and _is_anthropic_billing_block(exc):
            return LLMQuotaError(_ANTHROPIC_BILLING_MESSAGE)
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMAuthenticationError("Your Anthropic key is not permitted to use this model.")
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(
                "Anthropic rate limit reached. Please wait a moment and retry.",
                retry_after=_retry_after_seconds(getattr(exc, "response", None)),
            )
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMTimeoutError("The Anthropic request timed out. Please retry.")
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMConnectionError("Could not reach the Anthropic API. Check your network.")
        if isinstance(exc, anthropic.NotFoundError):
            return LLMConfigurationError(
                f"Model '{self.model}' was not found or is not available to your Anthropic account."
            )
        if isinstance(exc, anthropic.BadRequestError):
            return LLMBadRequestError("Anthropic rejected the request (HTTP 400).")
        if isinstance(exc, anthropic.InternalServerError):  # includes 529 overloaded
            return LLMServerError("Anthropic returned a server/overloaded error. Please retry.")
        if isinstance(exc, anthropic.APIStatusError):
            return LLMBadRequestError(f"Anthropic returned HTTP {exc.status_code}.")
        return LLMError("The Anthropic request failed.")

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
        except anthropic.AnthropicError as exc:
            raise self._translate_error(exc) from None
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

    def __init__(
        self,
        model: str,
        settings: Settings,
        *,
        credential: Credential | None = None,
        client: Any | None = None,
        http_client: Any | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, settings, **kwargs)
        if client is None:
            credential = _require_credential(credential, "gemini")
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise LLMConfigurationError(
                    "The 'google-genai' package is not installed. Run: pip install -e '.[gemini]'"
                ) from None
            options: dict[str, Any] = {"timeout": int(settings.request_timeout_s * 1000)}
            if http_client is not None:
                options["httpx_client"] = http_client
            client = genai.Client(
                api_key=credential.secret.get_secret_value(),
                # An explicit False stops GOOGLE_GENAI_USE_VERTEXAI / _ENTERPRISE in the server
                # environment from re-routing a session key to Vertex AI.
                vertexai=False if credential.is_session_key else None,
                http_options=types.HttpOptions(**options),
            )
        self.client = client

    def check_access(self) -> None:
        import httpx2
        from google.genai import errors

        self._count_request()
        try:
            self.client.models.get(model=self.model)
        except (errors.APIError, httpx2.TransportError) as exc:
            raise self._translate_error(exc) from None

    def _translate_error(self, exc: Exception) -> LLMError:
        import httpx2
        from google.genai import errors

        if isinstance(exc, errors.ClientError):
            code = getattr(exc, "code", None)
            # Gemini reports an invalid or expired key as HTTP 400 API_KEY_INVALID.
            if code in (401, 403) or (code == 400 and _GEMINI_KEY_PROBLEM.search(str(exc))):
                return LLMAuthenticationError(_rejected_key_message("Google Gemini"))
            if code == 429:
                return LLMRateLimitError("Gemini rate limit or quota reached. Please retry later.")
            if code == 404:
                return LLMConfigurationError(
                    f"Model '{self.model}' was not found or is not available to your Gemini key."
                )
            return LLMBadRequestError(f"Gemini rejected the request (HTTP {code}).")
        if isinstance(exc, errors.ServerError):
            return LLMServerError("Gemini returned a server error. Please retry.")
        if isinstance(exc, httpx2.TimeoutException):
            return LLMTimeoutError("The Gemini request timed out. Please retry.")
        if isinstance(exc, httpx2.TransportError):
            return LLMConnectionError("Could not reach the Gemini API. Check your network.")
        return LLMError("The Gemini request failed.")

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
        except (errors.APIError, httpx2.TransportError) as exc:
            raise self._translate_error(exc) from None

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


def create_provider(
    settings: Settings,
    *,
    credential: Credential | None = None,
    allow_offline_fallback: bool = False,
) -> ProviderStatus:
    """Instantiate the configured provider with ``credential``.

    The factory never looks up a key: the UI passes the session's credential from
    :func:`docintel.credentials.resolve_credential` and the evaluation runner passes the server's
    from :func:`docintel.credentials.server_credential`. Without one, a hosted provider can't be
    built. With ``allow_offline_fallback`` (used by the UI), a missing key or SDK falls back to the
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
        provider = classes[settings.provider](model, settings, credential=credential)
        return ProviderStatus(provider, settings.provider)
    except LLMConfigurationError as exc:
        if not allow_offline_fallback:
            raise
        return ProviderStatus(
            ExtractiveOfflineProvider(settings), settings.provider, exc.user_message
        )
