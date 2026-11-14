"""Multi-document comparison.

The context budget is split evenly between the documents so that no single document crowds
out the others. A document that fits its share is sent in full; a larger one is represented
by the passages most relevant to the user's focus (or, without a focus, by its passages in
document order up to its share), and the coverage report says which pages were included.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docintel.grounding import GroundingReport, validate_comparison
from docintel.llm_client import CallStats, LLMProvider, StructuredRequest
from docintel.models import Chunk, ComparisonOutput, SourcePassage
from docintel.prompting import format_document_list, format_source_ids, format_sources, load_prompt
from docintel.retrieval import chunks_to_passages, estimate_tokens
from docintel.session import DocumentWorkspace
from docintel.workflow_utils import CoverageReport, WorkflowError, build_coverage

MAX_COMPARE_DOCUMENTS = 4
DEFAULT_FOCUS = "all substantive similarities, differences, changes and conflicts"


@dataclass
class ComparisonResult:
    output: ComparisonOutput
    sources: list[SourcePassage]
    report: GroundingReport
    stats: CallStats | None
    coverage: CoverageReport
    provider_label: str
    offline: bool
    focus: str


def _fit(chunks: Sequence[Chunk], budget: int) -> list[Chunk]:
    chosen, used = [], 0
    for c in chunks:
        cost = estimate_tokens(c.text) + 30
        if used + cost > budget:
            continue
        chosen.append(c)
        used += cost
    return chosen


def compare_documents(
    workspace: DocumentWorkspace,
    provider: LLMProvider,
    doc_ids: Sequence[str],
    *,
    focus: str = "",
) -> ComparisonResult:
    settings = workspace.settings
    scope = workspace.resolve_scope(doc_ids)
    if len(scope) < 2:
        raise WorkflowError("Select at least two documents to compare.")
    if len(scope) > MAX_COMPARE_DOCUMENTS:
        raise WorkflowError(f"Compare at most {MAX_COMPARE_DOCUMENTS} documents at a time.")
    focus = (focus or "").strip()[:300]
    per_doc_budget = max(800, (settings.section_token_budget * 3 // 2) // len(scope))

    selected_chunks: list[Chunk] = []
    all_chunks: list[Chunk] = []
    for doc_id in scope:
        doc_chunks = workspace.chunks_for([doc_id])
        all_chunks.extend(doc_chunks)
        total = sum(estimate_tokens(c.text) + 30 for c in doc_chunks)
        if total <= per_doc_budget:
            picked = list(doc_chunks)
        elif focus:
            hits = workspace.search(focus, top_k=50, doc_ids=[doc_id])
            hit_ids = {h.chunk.chunk_id for h in hits}
            ranked = [h.chunk for h in hits] + [c for c in doc_chunks if c.chunk_id not in hit_ids]
            picked = sorted(_fit(ranked, per_doc_budget), key=lambda c: c.ordinal)
        else:
            picked = _fit(doc_chunks, per_doc_budget)
        selected_chunks.extend(picked)

    passages = chunks_to_passages(selected_chunks)
    all_passages = chunks_to_passages(all_chunks)
    coverage = build_coverage(all_passages, [passages], 1)
    if not coverage.complete:
        coverage.notes.append(
            "Large documents were represented by the passages most relevant to the focus (or their "
            "opening pages); differences on other pages may be missed."
        )
    template = load_prompt("comparison")
    system, user = template.render(
        sources=format_sources(passages),
        source_ids=format_source_ids(passages),
        document_list=format_document_list(passages),
        focus=focus or DEFAULT_FOCUS,
    )
    result = provider.generate(
        StructuredRequest(
            "comparison",
            system,
            user,
            ComparisonOutput,
            context={"sources": passages, "focus": focus},
        )
    )
    report = validate_comparison(result.output, passages)
    if not coverage.complete:
        report.warnings.append(coverage.summary_line())
    return ComparisonResult(
        output=result.output,
        sources=passages,
        report=report,
        stats=result.stats,
        coverage=coverage,
        provider_label=provider.label,
        offline=provider.is_offline,
        focus=focus or DEFAULT_FOCUS,
    )
