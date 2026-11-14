"""Grounded question answering over the workspace documents (retrieval-augmented generation)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from docintel.grounding import GroundingReport, validate_qa
from docintel.llm_client import CallStats, LLMProvider, StructuredRequest
from docintel.models import QAOutput, SourcePassage
from docintel.prompting import (
    ConversationTurn,
    format_document_list,
    format_history,
    format_source_ids,
    format_sources,
    qa_prompt,
)
from docintel.retrieval import select_context, to_source_passages
from docintel.session import DocumentWorkspace
from docintel.workflow_utils import WorkflowError


@dataclass
class RetrievalDiagnostics:
    retriever: str
    candidates: int
    estimated_context_tokens: int
    token_budget: int
    skipped_duplicates: int = 0
    skipped_for_budget: int = 0
    skipped_for_doc_cap: int = 0
    used_history_for_retrieval: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class QAResult:
    question: str
    output: QAOutput
    sources: list[SourcePassage]
    report: GroundingReport
    stats: CallStats | None
    prompt_label: str
    provider_label: str
    offline: bool
    retrieval: RetrievalDiagnostics


def answer_question(
    workspace: DocumentWorkspace,
    provider: LLMProvider,
    question: str,
    *,
    history: Sequence[ConversationTurn] = (),
    doc_ids: Sequence[str] | None = None,
    prompt_version: str | None = None,
    retriever: str | None = None,
) -> QAResult:
    settings = workspace.settings
    q = (question or "").strip()
    if not q:
        raise WorkflowError("Please enter a question.")
    if len(q) > settings.max_question_chars:
        raise WorkflowError(f"Questions are limited to {settings.max_question_chars} characters.")
    if not workspace.documents:
        raise WorkflowError(
            "Upload at least one PDF (or load the sample documents) before asking a question."
        )
    scope = workspace.resolve_scope(doc_ids)
    if not scope:
        raise WorkflowError("Select at least one document to search.")

    # Follow-ups such as "what about the second one?" need the previous question for retrieval.
    retrieval_query = q
    used_history = False
    if history:
        retrieval_query = f"{q} {history[-1].question}"
        used_history = True
    retriever_name = retriever or settings.retriever
    ranked = workspace.search(
        retrieval_query, top_k=max(settings.top_k * 3, 20), doc_ids=scope, retriever=retriever_name
    )
    selection = select_context(
        ranked,
        token_budget=settings.context_token_budget,
        max_chunks=settings.top_k,
        max_per_document=settings.max_chunks_per_document if len(scope) > 1 else None,
    )
    passages = to_source_passages(selection.selected)
    diagnostics = RetrievalDiagnostics(
        retriever=retriever_name,
        candidates=len(ranked),
        estimated_context_tokens=selection.estimated_tokens,
        token_budget=settings.context_token_budget,
        skipped_duplicates=selection.skipped_duplicates,
        skipped_for_budget=selection.skipped_for_budget,
        skipped_for_doc_cap=selection.skipped_for_doc_cap,
        used_history_for_retrieval=used_history,
        notes=list(selection.notes),
    )
    template = qa_prompt(prompt_version or settings.qa_prompt_version)

    if not passages:
        # Nothing in the documents shares any searchable term with the question: abstain
        # without spending a model call.
        output = QAOutput(
            status="insufficient_evidence",
            answer="None of the selected documents contain passages related to this question, so it "
            "cannot be answered from the uploaded documents.",
            claims=[],
            conflicts=[],
            missing_information=[q],
            confidence="high",
        )
        diagnostics.notes.append("No passage matched the question; the model was not called.")
        return QAResult(
            q,
            output,
            [],
            validate_qa(output, []),
            None,
            template.label,
            provider.label,
            provider.is_offline,
            diagnostics,
        )

    system, user = template.render(
        sources=format_sources(passages),
        source_ids=format_source_ids(passages),
        question=q,
        history=format_history(history, settings.history_turns),
        document_list=format_document_list(passages),
    )
    request = StructuredRequest(
        task="qa",
        system=system,
        user=user,
        response_model=QAOutput,
        context={"question": q, "sources": passages},
    )
    result = provider.generate(request)
    report = validate_qa(result.output, passages)
    return QAResult(
        question=q,
        output=result.output,
        sources=passages,
        report=report,
        stats=result.stats,
        prompt_label=template.label,
        provider_label=provider.label,
        offline=provider.is_offline,
        retrieval=diagnostics,
    )
