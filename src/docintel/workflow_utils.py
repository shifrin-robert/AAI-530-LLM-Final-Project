"""Helpers shared by the task workflows: errors, section planning and coverage reporting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from docintel.model_catalog import estimate_cost_usd
from docintel.models import SourcePassage
from docintel.retrieval import estimate_tokens


class WorkflowError(Exception):
    """A user-correctable problem with a request (no documents, empty question, ...)."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


def plan_sections(
    passages: Sequence[SourcePassage], token_budget: int
) -> list[list[SourcePassage]]:
    """Group consecutive passages (document order) into sections that fit ``token_budget``.

    A new section also starts at every document boundary so each section is about one document.
    """
    sections: list[list[SourcePassage]] = []
    current: list[SourcePassage] = []
    used = 0
    for p in passages:
        cost = estimate_tokens(p.text) + 30
        new_doc = bool(current) and current[-1].doc_id != p.doc_id
        if current and (used + cost > token_budget or new_doc):
            sections.append(current)
            current, used = [], 0
        current.append(p)
        used += cost
    if current:
        sections.append(current)
    return sections


def _page_ranges(pages: Sequence[int]) -> str:
    pages = sorted(set(pages))
    if not pages:
        return ""
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        out.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = p
    out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


@dataclass
class CoverageReport:
    """Which pages of which documents actually reached the model."""

    sections_total: int
    sections_processed: int
    pages_with_text: dict[str, list[int]]  # filename -> pages
    pages_covered: dict[str, list[int]]
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return all(
            set(pages) <= set(self.pages_covered.get(name, []))
            for name, pages in self.pages_with_text.items()
        )

    @property
    def uncovered(self) -> dict[str, str]:
        result = {}
        for name, pages in self.pages_with_text.items():
            missing = sorted(set(pages) - set(self.pages_covered.get(name, [])))
            if missing:
                result[name] = _page_ranges(missing)
        return result

    def summary_line(self) -> str:
        if self.complete:
            return f"Full coverage: all {sum(len(v) for v in self.pages_with_text.values())} pages with text were processed."
        parts = [f"{name}: pages {pages}" for name, pages in self.uncovered.items()]
        return "Partial coverage. Not processed: " + "; ".join(parts) + "."


def build_coverage(
    all_passages: Sequence[SourcePassage],
    processed: Sequence[Sequence[SourcePassage]],
    sections_total: int,
) -> CoverageReport:
    with_text: dict[str, set[int]] = {}
    for p in all_passages:
        with_text.setdefault(p.filename, set()).add(p.page_number)
    covered: dict[str, set[int]] = {}
    for section in processed:
        for p in section:
            covered.setdefault(p.filename, set()).add(p.page_number)
    return CoverageReport(
        sections_total=sections_total,
        sections_processed=len(processed),
        pages_with_text={k: sorted(v) for k, v in with_text.items()},
        pages_covered={k: sorted(v) for k, v in covered.items()},
    )


@dataclass
class CallPlan:
    """Pre-flight estimate shown to the user before multi-call operations."""

    calls: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float | None
    truncated: bool


def estimate_plan(
    sections: Sequence[Sequence[SourcePassage]],
    *,
    model: str,
    offline: bool,
    max_sections: int,
    prompt_overhead_tokens: int = 1200,
    output_tokens_per_call: int = 1200,
    reduce_step: bool = False,
) -> CallPlan:
    used = list(sections)[:max_sections]
    calls = len(used) + (1 if reduce_step and len(used) > 1 else 0)
    input_tokens = sum(
        sum(estimate_tokens(p.text) + 30 for p in s) + prompt_overhead_tokens for s in used
    )
    if reduce_step and len(used) > 1:
        input_tokens += prompt_overhead_tokens + output_tokens_per_call * len(used)
    output_tokens = output_tokens_per_call * calls
    cost = 0.0 if offline else estimate_cost_usd(model, input_tokens, output_tokens)
    return CallPlan(
        calls, input_tokens, output_tokens, cost, truncated=len(sections) > max_sections
    )
