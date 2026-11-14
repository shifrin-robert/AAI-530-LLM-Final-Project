"""Grounded summarization with hierarchical (map-reduce) processing for long documents.

* If the whole selection fits in one section budget: one call with ``prompts/summarization.md``.
* Otherwise: one *map* call per section (``summarization_section.md``) producing cited notes,
  then one *reduce* call (``summarization_combine.md``) that merges them, keeping the original
  source IDs so every point stays traceable to a page.
* At most ``max_sections`` sections are processed per run to bound cost. If a document needs
  more, the result is explicitly marked as partial and lists the pages that were not covered;
  nothing is silently dropped.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from docintel.grounding import GroundingReport, extract_inline_ids, validate_summary
from docintel.llm_client import CallStats, LLMProvider, StructuredRequest
from docintel.models import SectionNotes, SourcePassage, SummaryOutput
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

DEFAULT_FOCUS = "a balanced overview of the whole document"


@dataclass
class SummaryResult:
    output: SummaryOutput
    sources: list[SourcePassage]
    report: GroundingReport
    stats: CallStats | None
    coverage: CoverageReport
    method: str  # "single_pass" | "map_reduce"
    provider_label: str
    offline: bool
    map_warnings: list[str] = field(default_factory=list)


def _prepare(
    workspace: DocumentWorkspace, doc_ids: Sequence[str] | None
) -> tuple[list[SourcePassage], list[list[SourcePassage]]]:
    scope = workspace.resolve_scope(doc_ids)
    if not scope:
        raise WorkflowError("Select at least one document to summarize.")
    passages = chunks_to_passages(workspace.chunks_for(scope))
    if not passages:
        raise WorkflowError("The selected documents contain no extractable text to summarize.")
    return passages, plan_sections(passages, workspace.settings.section_token_budget)


def plan_summary(
    workspace: DocumentWorkspace, provider: LLMProvider, doc_ids: Sequence[str] | None
) -> CallPlan:
    _, sections = _prepare(workspace, doc_ids)
    return estimate_plan(
        sections,
        model=provider.model,
        offline=provider.is_offline,
        max_sections=workspace.settings.max_sections,
        reduce_step=True,
    )


def summarize_documents(
    workspace: DocumentWorkspace,
    provider: LLMProvider,
    doc_ids: Sequence[str] | None = None,
    *,
    focus: str = "",
) -> SummaryResult:
    settings = workspace.settings
    focus = (focus or "").strip()[:300] or DEFAULT_FOCUS
    passages, sections = _prepare(workspace, doc_ids)
    processed = sections[: settings.max_sections]
    coverage = build_coverage(passages, processed, len(sections))
    if len(sections) > len(processed):
        coverage.notes.append(
            f"Only {len(processed)} of {len(sections)} sections were summarized because of the "
            f"per-run limit (DOCINTEL_MAX_SECTIONS={settings.max_sections})."
        )
    used = [p for s in processed for p in s]
    stats: list[CallStats] = []
    map_warnings: list[str] = []

    if len(processed) == 1:
        template = load_prompt("summarization")
        system, user = template.render(
            sources=format_sources(used),
            source_ids=format_source_ids(used),
            document_list=format_document_list(used),
            focus=focus,
        )
        result = provider.generate(
            StructuredRequest(
                "summary_reduce",
                system,
                user,
                SummaryOutput,
                context={"sources": used, "focus": focus},
            )
        )
        stats.append(result.stats)
        output, method = result.output, "single_pass"
    else:
        section_template = load_prompt("summarization_section")
        notes: list[SectionNotes] = []
        for i, section in enumerate(processed, start=1):
            label = (
                f"Section {i} of {len(processed)}: {section[0].filename}, pages "
                f"{section[0].page_number}-{section[-1].page_number}"
            )
            system, user = section_template.render(
                sources=format_sources(section),
                source_ids=format_source_ids(section),
                section_label=label,
                focus=focus,
            )
            result = provider.generate(
                StructuredRequest(
                    "summary_map",
                    system,
                    user,
                    SectionNotes,
                    context={"sources": section, "focus": focus},
                )
            )
            stats.append(result.stats)
            section_ids = {p.source_id for p in section}
            note_ids = set(extract_inline_ids(result.output.section_summary)) | {
                sid
                for group in (
                    result.output.key_points,
                    result.output.action_items,
                    result.output.obligations,
                    result.output.risks,
                )
                for item in group
                for sid in item.source_ids
            }
            stray = sorted(note_ids - section_ids)
            if stray:
                map_warnings.append(
                    f"Section {i} notes cited IDs outside the section: {', '.join(stray)}"
                )
            notes.append(result.output)

        combine_template = load_prompt("summarization_combine")
        notes_text = "\n\n".join(
            f'<section_notes index="{i}">\n{json.dumps(n.model_dump(), ensure_ascii=False, indent=1)}\n</section_notes>'
            for i, n in enumerate(notes, start=1)
        )
        system, user = combine_template.render(
            section_notes=notes_text,
            source_ids=format_source_ids(used),
            document_list=format_document_list(used),
            coverage_note=coverage.summary_line(),
            focus=focus,
        )
        result = provider.generate(
            StructuredRequest(
                "summary_reduce",
                system,
                user,
                SummaryOutput,
                context={"sources": used, "section_notes": notes, "focus": focus},
            )
        )
        stats.append(result.stats)
        output, method = result.output, "map_reduce"

    report = validate_summary(output, used)
    report.warnings.extend(map_warnings)
    if not coverage.complete:
        report.warnings.append(coverage.summary_line())
    return SummaryResult(
        output=output,
        sources=used,
        report=report,
        stats=CallStats.combine(stats),
        coverage=coverage,
        method=method,
        provider_label=provider.label,
        offline=provider.is_offline,
        map_warnings=map_warnings,
    )
