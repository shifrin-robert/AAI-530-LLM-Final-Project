"""Priced catalog of the models compared in docs/API_SELECTION_REPORT.md.

All prices are USD per 1 million tokens (standard, non-batch tier) and were read from the
providers' official pricing pages on 2026-11-13. Prices change: re-verify before relying
on cost estimates. Model identifiers live here (and in configuration) only, so that no
other module hardcodes a model name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

VERIFIED_ON = "2026-11-13"

OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"
ANTHROPIC_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
GEMINI_PRICING_URL = "https://aistudio.google.com/docs/pricing"


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None
    context_window: int
    max_output_tokens: int
    tier: str  # "economy" | "mid" | "frontier"
    reasoning_controls: tuple[str, ...] = ()
    status: str = "active"
    notes: str = ""
    source_url: str = ""
    # Some models charge more above a prompt-length threshold.
    long_prompt_threshold_tokens: int | None = None
    long_prompt_input_per_mtok: float | None = None
    long_prompt_output_per_mtok: float | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def estimate_cost(
        self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
    ) -> float:
        """Estimated USD cost of one request. Output tokens include reasoning tokens."""
        input_rate = self.input_per_mtok
        output_rate = self.output_per_mtok
        if (
            self.long_prompt_threshold_tokens is not None
            and input_tokens > self.long_prompt_threshold_tokens
        ):
            input_rate = self.long_prompt_input_per_mtok or input_rate
            output_rate = self.long_prompt_output_per_mtok or output_rate
        cached = max(0, min(cached_input_tokens, input_tokens))
        uncached = input_tokens - cached
        cached_rate = (
            self.cached_input_per_mtok if self.cached_input_per_mtok is not None else input_rate
        )
        return (
            uncached * input_rate + cached * cached_rate + output_tokens * output_rate
        ) / 1_000_000


CATALOG: tuple[ModelInfo, ...] = (
    # ----------------------------------------------------------------- OpenAI
    ModelInfo(
        provider="openai",
        model_id="gpt-6-luna",
        display_name="GPT-6 Luna",
        input_per_mtok=0.10,
        cached_input_per_mtok=0.01,
        output_per_mtok=0.50,
        context_window=1_050_000,
        max_output_tokens=128_000,
        tier="economy",
        reasoning_controls=("none", "low", "medium", "high", "xhigh", "max"),
        notes="Reasoning model; default effort medium. OpenAI positions it for cost-sensitive, "
        "high-volume workloads. Knowledge cutoff May 18, 2026.",
        source_url=OPENAI_PRICING_URL,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        input_per_mtok=0.20,
        cached_input_per_mtok=0.02,
        output_per_mtok=1.20,
        context_window=1_050_000,
        max_output_tokens=128_000,
        tier="economy",
        reasoning_controls=("none", "low", "medium", "high", "xhigh", "max"),
        source_url=OPENAI_PRICING_URL,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-6.1-terra",
        display_name="GPT-6.1 Terra",
        input_per_mtok=1.00,
        cached_input_per_mtok=0.05,
        output_per_mtok=5.00,
        context_window=1_050_000,
        max_output_tokens=128_000,
        tier="mid",
        reasoning_controls=("none", "low", "medium", "high", "xhigh", "max"),
        notes="Knowledge cutoff Jun 01, 2026.",
        source_url=OPENAI_PRICING_URL,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-6.1-sol",
        display_name="GPT-6.1 Sol",
        input_per_mtok=2.00,
        cached_input_per_mtok=0.10,
        output_per_mtok=10.00,
        context_window=1_050_000,
        max_output_tokens=128_000,
        tier="mid",
        reasoning_controls=("low", "medium", "high", "xhigh", "max"),
        source_url=OPENAI_PRICING_URL,
    ),
    ModelInfo(
        provider="openai",
        model_id="gpt-6-astra",
        display_name="GPT-6 Astra",
        input_per_mtok=10.00,
        cached_input_per_mtok=1.00,
        output_per_mtok=50.00,
        context_window=1_050_000,
        max_output_tokens=128_000,
        tier="frontier",
        reasoning_controls=("low", "medium", "high", "xhigh", "max"),
        notes="Flagship; listed for reference only.",
        source_url=OPENAI_PRICING_URL,
    ),
    # -------------------------------------------------------------- Anthropic
    ModelInfo(
        provider="anthropic",
        model_id="claude-haiku-5-5",
        display_name="Claude Haiku 5.5",
        input_per_mtok=0.10,
        cached_input_per_mtok=0.01,
        output_per_mtok=0.50,
        context_window=1_000_000,
        max_output_tokens=128_000,
        tier="economy",
        notes="Prompts over 100k tokens are billed at $0.50 input / $2.50 output.",
        source_url=ANTHROPIC_PRICING_URL,
        long_prompt_threshold_tokens=100_000,
        long_prompt_input_per_mtok=0.50,
        long_prompt_output_per_mtok=2.50,
    ),
    ModelInfo(
        provider="anthropic",
        model_id="claude-sonnet-5-5",
        display_name="Claude Sonnet 5.5",
        input_per_mtok=2.00,
        cached_input_per_mtok=0.10,
        output_per_mtok=10.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        tier="mid",
        source_url=ANTHROPIC_PRICING_URL,
    ),
    ModelInfo(
        provider="anthropic",
        model_id="claude-opus-5-5",
        display_name="Claude Opus 5.5",
        input_per_mtok=4.00,
        cached_input_per_mtok=0.20,
        output_per_mtok=20.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        tier="frontier",
        notes="Listed for reference only.",
        source_url=ANTHROPIC_PRICING_URL,
    ),
    # ----------------------------------------------------------------- Google
    ModelInfo(
        provider="gemini",
        model_id="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        input_per_mtok=0.25,
        cached_input_per_mtok=0.025,
        output_per_mtok=1.50,
        context_window=1_048_576,
        max_output_tokens=65_536,
        tier="economy",
        reasoning_controls=("minimal", "low", "medium", "high"),
        notes="Free tier available, but free-tier prompts/responses are used to improve Google "
        "products and may be human-reviewed. Output price includes thinking tokens.",
        source_url=GEMINI_PRICING_URL,
    ),
    ModelInfo(
        provider="gemini",
        model_id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash-Lite",
        input_per_mtok=0.30,
        cached_input_per_mtok=0.03,
        output_per_mtok=2.50,
        context_window=1_048_576,
        max_output_tokens=65_536,
        tier="economy",
        reasoning_controls=("minimal", "low", "medium", "high"),
        source_url=GEMINI_PRICING_URL,
    ),
    ModelInfo(
        provider="gemini",
        model_id="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        input_per_mtok=0.75,
        cached_input_per_mtok=0.075,
        output_per_mtok=3.75,
        context_window=1_048_576,
        max_output_tokens=65_536,
        tier="mid",
        reasoning_controls=("low", "medium", "high"),
        notes="Price doubles to $1.50 / $7.50 on 2027-01-01.",
        source_url=GEMINI_PRICING_URL,
    ),
)

DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "openai": "gpt-6-luna",
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-3.1-flash-lite",
    "mock": "extractive-baseline",
}


def get_model_info(model_id: str) -> ModelInfo | None:
    for info in CATALOG:
        if info.model_id == model_id:
            return info
    return None


def models_for_provider(provider: str) -> list[ModelInfo]:
    return [info for info in CATALOG if info.provider == provider]


def estimate_cost_usd(
    model_id: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0
) -> float | None:
    """Return the estimated cost, or None when the model is not in the priced catalog."""
    info = get_model_info(model_id)
    if info is None:
        return None
    return info.estimate_cost(input_tokens, output_tokens, cached_input_tokens)
