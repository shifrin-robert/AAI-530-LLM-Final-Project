"""Structured information extraction with source references.

The selected documents are processed section by section (so long documents are covered, up to
``max_sections`` per run), each section's output is validated against its own sources, and the
results are merged and de-duplicated deterministically in code (not by the model).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from docintel.grounding import GroundingReport, validate_extraction
from docintel.llm_client import CallStats, LLMProvider, StructuredRequest
from docintel.models import EXTRACTION_CATEGORIES, ExtractedItem, ExtractionOutput, SourcePassage
from docintel.prompting import format_document_list, format_source_ids, format_sources, load_prompt
from docintel.retrieval import chunks_to_passages
from docintel.session import DocumentWorkspace
from docintel.workflow_utils import (
    CallPlan,
    CoverageReport,
    WorkflowError,
    build_coverage,
    estimate_plan,
    plan_sections,
)

CATEGORY_LABELS = {
    "people": "People",
    "organizations": "Organizations",
    "dates": "Dates",
    "monetary_amounts": "Monetary amounts",
    "responsibilities": "Responsibilities",
    "obligations": "Obligations",
    "decisions": "Decisions",
    "risks": "Risks",
    "key_facts": "Key facts",
}


@dataclass
class ExtractionResult:
    output: ExtractionOutput
    sources: list[SourcePassage]
    report: GroundingReport
    stats: CallStats | None
    coverage: CoverageReport
    categories: list[str]
    provider_label: str
    offline: bool
    duplicates_removed: int = 0
    notes: list[str] = field(default_factory=list)


def _dedupe_key(item: ExtractedItem) -> str:
    basis = item.normalized_value or item.value
    return re.sub(r"\s+", " ", basis).strip().lower()


def merge_extractions(outputs: Sequence[ExtractionOutput]) -> tuple[ExtractionOutput, int]:
    merged: dict[str, list[ExtractedItem]] = {c: [] for c in EXTRACTION_CATEGORIES}
    seen: dict[str, set[str]] = {c: set() for c in EXTRACTION_CATEGORIES}
    removed = 0
    for out in outputs:
        for category in EXTRACTION_CATEGORIES:
            for item in getattr(out, category):
                key = _dedupe_key(item)
                if key in seen[category]:
                    removed += 1
                    continue
                seen[category].add(key)
                merged[category].append(item)
    not_found = [c for c in EXTRACTION_CATEGORIES if not merged[c]]
    return ExtractionOutput(**merged, not_found=not_found), removed


def _prepare(workspace: DocumentWorkspace, doc_ids: Sequence[str] | None):
    scope = workspace.resolve_scope(doc_ids)
    if not scope:
        raise WorkflowError("Select at least one document for extraction.")
    passages = chunks_to_passages(workspace.chunks_for(scope))
    if not passages:
        raise WorkflowError("The selected documents contain no extractable text.")
    return passages, plan_sections(passages, workspace.settings.section_token_budget)


def plan_extraction(
    workspace: DocumentWorkspace, provider: LLMProvider, doc_ids: Sequence[str] | None
) -> CallPlan:
    _, sections = _prepare(workspace, doc_ids)
    return estimate_plan(
        sections,
        model=provider.model,
        offline=provider.is_offline,
        max_sections=workspace.settings.max_sections,
    )


def extract_information(
    workspace: DocumentWorkspace,
    provider: LLMProvider,
    doc_ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
) -> ExtractionResult:
    settings = workspace.settings
    wanted = [c for c in (categories or EXTRACTION_CATEGORIES) if c in EXTRACTION_CATEGORIES]
    if not wanted:
        raise WorkflowError("Select at least one category to extract.")
    passages, sections = _prepare(workspace, doc_ids)
    processed = sections[: settings.max_sections]
    coverage = build_coverage(passages, processed, len(sections))
    template = load_prompt("extraction")
    outputs: list[ExtractionOutput] = []
    stats: list[CallStats] = []
    for section in processed:
        system, user = template.render(
            sources=format_sources(section),
            source_ids=format_source_ids(section),
            document_list=format_document_list(section),
            categories=", ".join(wanted),
        )
        result = provider.generate(
            StructuredRequest(
                "extraction",
                system,
                user,
                ExtractionOutput,
                context={"sources": section, "categories": wanted},
            )
        )
        stats.append(result.stats)
        # Keep only requested categories even if the model filled others.
        filtered = {
            c: (getattr(result.output, c) if c in wanted else []) for c in EXTRACTION_CATEGORIES
        }
        outputs.append(ExtractionOutput(**filtered, not_found=[]))
    merged, removed = merge_extractions(outputs)
    merged = merged.model_copy(update={"not_found": [c for c in wanted if not getattr(merged, c)]})
    used = [p for s in processed for p in s]
    report = validate_extraction(merged, used)
    notes = []
    if not coverage.complete:
        notes.append(coverage.summary_line())
        report.warnings.append(coverage.summary_line())
    return ExtractionResult(
        output=merged,
        sources=used,
        report=report,
        stats=CallStats.combine(stats),
        coverage=coverage,
        categories=wanted,
        provider_label=provider.label,
        offline=provider.is_offline,
        duplicates_removed=removed,
        notes=notes,
    )
