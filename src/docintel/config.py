"""Application configuration loaded from environment variables (optionally via a .env file).

API keys are deliberately *not* stored on the Settings object: they are read on demand with
:func:`get_api_key` and wrapped in ``SecretStr`` so they never appear in logs or reprs.
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
    qa_prompt_version: str = "v3"
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
        if self.qa_prompt_version not in {"v1", "v2", "v3"}:
            problems.append("DOCINTEL_QA_PROMPT_VERSION must be v1, v2 or v3")
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
        """Build settings from environment variables (``DOCINTEL_*``)."""
        if env is None:
            if load_dotenv_file:
                _load_dotenv()
            env = os.environ
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
            values[field_name] = raw.lower() if field_name in {"provider", "retriever"} else raw
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


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_api_key(provider: str, env: Mapping[str, str] | None = None) -> SecretStr | None:
    """Return the API key for ``provider`` (or None). Never log the returned value."""
    var = API_KEY_ENV_VARS.get(provider)
    if var is None:
        return None
    source = os.environ if env is None else env
    value = (source.get(var) or "").strip()
    if provider == "gemini" and not value:
        value = (source.get("GOOGLE_API_KEY") or "").strip()
    return SecretStr(value) if value else None
