"""Application configuration loaded from environment variables and an optional .env file.

API keys are deliberately *not* stored on the Settings object. Keys typed in the browser belong to
that session (see :mod:`docintel.credentials`). Keys in the server environment or ``.env`` are read
on demand by :func:`server_api_key`, wrapped in ``SecretStr``, and used only in owner mode or by
the command-line evaluation runner. Reading ``.env`` never copies its values into ``os.environ``,
so the provider SDKs cannot pick them up on their own.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, model_validator

from docintel.model_catalog import DEFAULT_MODEL_BY_PROVIDER

ProviderName = Literal["openai", "anthropic", "gemini", "mock"]
RetrieverName = Literal["bm25", "char_ngram", "hybrid"]
# "byok": every browser session enters its own API key; server keys are never used.
# "owner": sessions without their own key use the server's keys (the key owner's local use, or a
# private deployment whose users are authorized to bill the owner's account).
KeyMode = Literal["byok", "owner"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
FIXTURES_DIR = PROJECT_ROOT / "evaluation" / "fixtures"

API_KEY_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class ConfigError(ValueError):
    """Raised when an environment variable holds an invalid value."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Provider / model
    provider: ProviderName = "openai"
    key_mode: KeyMode = "byok"
    model: str | None = None
    reasoning_effort: str | None = "low"
    temperature: float | None = None

    # Reliability and cost guards
    request_timeout_s: float = 60.0
    max_retries: int = 2
    retry_backoff_base_s: float = 1.0
    retry_backoff_max_s: float = 20.0
    max_output_tokens: int = 4000
    max_requests_per_session: int = 200

    # Upload limits
    max_file_mb: float = 20.0
    max_documents: int = 10
    max_pages_per_document: int = 300
    max_total_pages: int = 1000

    # Chunking / retrieval
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retriever: RetrieverName = "hybrid"
    top_k: int = 8
    context_token_budget: int = 6000
    max_chunks_per_document: int = 5

    # Summarization / extraction coverage control
    section_token_budget: int = 6000
    max_sections: int = 12

    # Prompts and conversation
    qa_prompt_version: str = "v2"
    max_question_chars: int = 2000
    history_turns: int = 3

    @model_validator(mode="after")
    def _check_ranges(self) -> Settings:
        problems: list[str] = []
        if self.chunk_size < 200:
            problems.append("DOCINTEL_CHUNK_SIZE must be at least 200 characters")
        if not 0 <= self.chunk_overlap < self.chunk_size // 2:
            problems.append("DOCINTEL_CHUNK_OVERLAP must be >= 0 and less than half the chunk size")
        if self.top_k < 1:
            problems.append("DOCINTEL_TOP_K must be at least 1")
        if self.context_token_budget < 500:
            problems.append("DOCINTEL_CONTEXT_TOKEN_BUDGET must be at least 500")
        if self.max_retries < 0 or self.max_retries > 6:
            problems.append("DOCINTEL_MAX_RETRIES must be between 0 and 6")
        if self.request_timeout_s <= 0:
            problems.append("DOCINTEL_REQUEST_TIMEOUT_S must be positive")
        if self.max_file_mb <= 0 or self.max_documents < 1 or self.max_pages_per_document < 1:
            problems.append("upload limits must be positive")
        if self.qa_prompt_version not in {"v1", "v2"}:
            problems.append("DOCINTEL_QA_PROMPT_VERSION must be v1 or v2")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODEL_BY_PROVIDER[self.provider]

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_mb * 1024 * 1024)

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, load_dotenv_file: bool = True
    ) -> Settings:
        """Build settings from ``DOCINTEL_*`` variables (real environment first, then ``.env``)."""
        if env is None:
            env = server_environment() if load_dotenv_file else dict(os.environ)
        values: dict[str, object] = {}
        for field_name in cls.model_fields:
            raw = env.get(f"DOCINTEL_{field_name.upper()}")
            if raw is None:
                continue
            raw = raw.strip()
            if raw == "":
                # Empty means "use the default" except for optional fields where it means None.
                if field_name in {"model", "reasoning_effort", "temperature"}:
                    values[field_name] = None
                continue
            lowercase = field_name in {"provider", "retriever", "key_mode"}
            values[field_name] = raw.lower() if lowercase else raw
        try:
            return cls(**values)
        except ValidationError as exc:
            details = "; ".join(
                f"DOCINTEL_{'.'.join(str(p) for p in err['loc']).upper() or 'SETTINGS'}: {err['msg']}"
                for err in exc.errors()
            )
            raise ConfigError(f"Invalid DocIntel configuration: {details}") from None

    def with_overrides(self, **changes: object) -> Settings:
        data = self.model_dump()
        data.update(changes)
        return Settings(**data)


def read_dotenv(path: Path) -> dict[str, str]:
    """Return the variables in a .env file without copying them into ``os.environ``."""
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
        return {}
    return {name: value for name, value in dotenv_values(path).items() if value is not None}


def _dotenv_values() -> dict[str, str]:
    return read_dotenv(PROJECT_ROOT / ".env")


def server_environment() -> dict[str, str]:
    """The server's configuration: the project's .env file, overridden by real variables."""
    return {**_dotenv_values(), **os.environ}


def get_api_key(provider: str, env: Mapping[str, str]) -> SecretStr | None:
    """Return the API key for ``provider`` found in ``env`` (or None). Never log the value."""
    var = API_KEY_ENV_VARS.get(provider)
    if var is None:
        return None
    value = (env.get(var) or "").strip()
    if provider == "gemini" and not value:
        value = (env.get("GOOGLE_API_KEY") or "").strip()
    return SecretStr(value) if value else None


def server_api_key(provider: str) -> SecretStr | None:
    """The key configured on the server (environment or .env) for ``provider``.

    Only for owner mode and the command-line evaluation runner. In BYOK mode a browser session
    must never be given this key: see :func:`docintel.credentials.resolve_credential`.
    """
    return get_api_key(provider, server_environment())
