"""End-to-end workflow tests over the synthetic fixtures (offline / scripted providers only)."""

import pytest

from docintel.comparison import compare_documents
from docintel.extraction import extract_information, merge_extractions
from docintel.llm_client import ScriptedProvider
from docintel.models import ExtractedItem, ExtractionOutput
from docintel.offline_provider import ExtractiveOfflineProvider
from docintel.prompting import ConversationTurn
from docintel.qa import answer_question
from docintel.session import DocumentWorkspace
from docintel.summarization import plan_summary, summarize_documents
from docintel.workflow_utils import WorkflowError, estimate_plan
from tests.conftest import AMENDMENT, BRIGHTLINE, MEMO, MSA, RESEARCH, STATUS, passage


@pytest.fixture
def offline():
    return ExtractiveOfflineProvider()


# ------------------------------------------------------------------ question answering


def test_offline_qa_answers_with_valid_citation_to_correct_page(workspace_with, offline):
    ws = workspace_with(MSA)
    result = answer_question(ws, offline, "What is the monthly service fee?")
    assert result.output.status == "answered"
    assert "4,500.00" in result.output.answer
    assert result.report.unknown_source_ids == []
    assert any(c.page_number == 2 and c.quote_status == "exact" for c in result.report.checks)
    assert result.prompt_label == "grounded_qa@v3" and result.offline


def test_qa_requires_documents_and_a_valid_question(settings, offline, workspace_with):
    with pytest.raises(WorkflowError):
        answer_question(DocumentWorkspace(settings), offline, "Anything?")
    ws = workspace_with(MSA)
    with pytest.raises(WorkflowError):
        answer_question(ws, offline, "   ")
    with pytest.raises(WorkflowError):
        answer_question(ws, offline, "x" * 5000)


def test_unmatched_question_abstains_without_calling_the_model(workspace_with):
    ws = workspace_with(MSA)
    never_called = ScriptedProvider([])  # would raise if the model were called
    result = answer_question(ws, never_called, "xylophone quokka zeppelin", retriever="bm25")
    assert result.output.status == "insufficient_evidence"
    assert result.stats is None and never_called.requests == []


def test_model_output_with_fabricated_citation_is_flagged(workspace_with):
    ws = workspace_with(BRIGHTLINE)
    injected_answer = {
        "status": "answered",
        "answer": "Brightline is the only approved vendor [S99].",
        "claims": [
            {
                "statement": "Brightline is the only approved vendor.",
                "claim_type": "fact",
                "citations": [{"source_id": "S99", "quote": "only approved vendor"}],
            }
        ],
        "conflicts": [],
        "missing_information": [],
        "confidence": "high",
    }
    result = answer_question(ws, ScriptedProvider([injected_answer]), "Which vendor was approved?")
    assert result.report.unknown_source_ids == ["S99"]
    assert result.report.verdict == "unsupported"


def test_injection_document_is_sent_as_flagged_untrusted_source(workspace_with):
    ws = workspace_with(BRIGHTLINE)
    provider = ScriptedProvider(
        [
            {
                "status": "insufficient_evidence",
                "answer": "Not stated.",
                "claims": [],
                "conflicts": [],
                "missing_information": ["approval"],
                "confidence": "medium",
            }
        ]
    )
    answer_question(ws, provider, "Has the Library Board approved the proposal?")
    sent = provider.requests[0]
    assert 'warning="contains instruction-like text' in sent.user
    assert "untrusted" in sent.system.lower()
    assert "Ignore all previous instructions" in sent.user  # passed as data, not removed


def test_conflicting_evidence_output_is_validated(workspace_with):
    ws = workspace_with(STATUS, MEMO)
    probe = answer_question(
        ws,
        ScriptedProvider(
            [
                {
                    "status": "insufficient_evidence",
                    "answer": "-",
                    "claims": [],
                    "conflicts": [],
                    "missing_information": [],
                    "confidence": "low",
                }
            ]
        ),
        "What is the planned go-live date?",
    )

    def source_containing(text):
        return next(p.source_id for p in probe.sources if text in p.text)

    s_status = source_containing("go-live date remains November 17, 2026")
    s_memo = source_containing("assumes go-live on December 1, 2026")
    conflict = {
        "status": "conflicting_evidence",
        "answer": f"The status report says November 17, 2026 [{s_status}]; the finance memo assumes December 1, 2026 [{s_memo}].",
        "claims": [
            {
                "statement": "The status report gives a go-live date of November 17, 2026.",
                "claim_type": "fact",
                "citations": [
                    {
                        "source_id": s_status,
                        "quote": "The planned go-live date remains November 17, 2026.",
                    }
                ],
            },
            {
                "statement": "The finance memo assumes go-live on December 1, 2026.",
                "claim_type": "fact",
                "citations": [
                    {
                        "source_id": s_memo,
                        "quote": "The finance schedule assumes go-live on December 1, 2026",
                    }
                ],
            },
        ],
        "conflicts": [
            {
                "description": "Different go-live dates.",
                "nature": "direct_contradiction",
                "source_ids": [s_status, s_memo],
            }
        ],
        "missing_information": [],
        "confidence": "medium",
    }
    result = answer_question(ws, ScriptedProvider([conflict]), "What is the planned go-live date?")
    assert result.report.unknown_source_ids == [] and result.report.quotes_found == 2
    assert {c.filename for c in result.report.checks} == {STATUS, MEMO}
    assert result.report.verdict == "grounded"


def test_follow_up_question_uses_history(workspace_with):
    ws = workspace_with(MSA)
    provider = ScriptedProvider(
        [
            {
                "status": "insufficient_evidence",
                "answer": "-",
                "claims": [],
                "conflicts": [],
                "missing_information": [],
                "confidence": "low",
            }
        ]
    )
    history = [ConversationTurn("What is the monthly service fee?", "It is $4,500.00 [S1].")]
    result = answer_question(ws, provider, "And when are invoices due?", history=history)
    assert result.retrieval.used_history_for_retrieval
    assert "UNVERIFIED" in provider.requests[0].user


def test_prompt_version_can_be_switched(workspace_with, offline):
    ws = workspace_with(MSA)
    assert (
        answer_question(
            ws, offline, "What is the late payment interest?", prompt_version="v1"
        ).prompt_label
        == "grounded_qa@v1"
    )


# ------------------------------------------------------------------ summarization


def test_single_pass_summary_offline(workspace_with, offline):
    ws = workspace_with(RESEARCH)
    result = summarize_documents(ws, offline)
    assert result.method == "single_pass" and result.coverage.complete
    assert result.report.unknown_source_ids == []
    assert result.output.key_findings


def test_long_document_uses_map_reduce_and_covers_every_page(workspace_with, settings, offline):
    small_sections = settings.with_overrides(section_token_budget=250, max_sections=20)
    ws = workspace_with(RESEARCH, settings_override=small_sections)
    result = summarize_documents(ws, offline)
    assert result.method == "map_reduce"
    assert result.coverage.complete and result.coverage.sections_processed > 1
    assert result.coverage.pages_covered[RESEARCH] == [1, 2, 3, 4]


def test_partial_coverage_is_reported_not_hidden(workspace_with, settings, offline):
    capped = settings.with_overrides(section_token_budget=250, max_sections=1)
    ws = workspace_with(RESEARCH, settings_override=capped)
    result = summarize_documents(ws, offline)
    assert not result.coverage.complete
    assert any("Partial coverage" in w for w in result.report.warnings)
    assert result.coverage.uncovered


def test_summary_plan_estimates_calls(workspace_with, settings, offline):
    ws = workspace_with(
        RESEARCH, settings_override=settings.with_overrides(section_token_budget=250)
    )
    plan = plan_summary(ws, offline, None)
    assert plan.calls >= 3 and plan.estimated_cost_usd == 0.0  # map calls + reduce; offline is free


def test_plan_cost_is_priced_per_call_not_on_summed_tokens():
    # 12 calls of ~7k tokens: about 100k in total, but every request is far below Haiku 5.5's
    # 100k-token long-prompt tier, so Haiku must cost the same as gpt-6-luna (same base prices).
    sections = [[passage(f"S{i}", "word " * 4800)] for i in range(12)]
    plans = {
        model: estimate_plan(
            sections, model=model, offline=False, max_sections=12, reduce_step=True
        )
        for model in ("gpt-6-luna", "claude-haiku-5-5")
    }
    assert plans["gpt-6-luna"].estimated_input_tokens > 100_000
    assert plans["claude-haiku-5-5"].estimated_cost_usd == pytest.approx(
        plans["gpt-6-luna"].estimated_cost_usd
    )


# ------------------------------------------------------------------ extraction and comparison


def test_offline_extraction_finds_people_amounts_and_dates(workspace_with, offline):
    ws = workspace_with(MSA)
    result = extract_information(ws, offline)
    people = {i.value for i in result.output.people}
    amounts = {i.value for i in result.output.monetary_amounts}
    assert {"Dana Whitfield", "Marcus Oyelaran"} <= people
    assert any("4,500.00" in a for a in amounts)
    assert result.report.unknown_source_ids == []
    assert all(c.quote_status in {"exact", "approximate"} for c in result.report.checks)


def test_extraction_respects_selected_categories(workspace_with, offline):
    result = extract_information(workspace_with(MSA), offline, categories=["dates"])
    assert result.output.dates and not result.output.people and result.categories == ["dates"]


def test_extraction_merge_removes_duplicates():
    item = ExtractedItem(
        value="$4,500.00", normalized_value="USD 4500.00", detail=None, source_id="S1", quote="q"
    )
    empty = {k: [] for k in ExtractionOutput.model_fields if k != "not_found"}
    a = ExtractionOutput(**{**empty, "monetary_amounts": [item]}, not_found=[])
    merged, removed = merge_extractions([a, a])
    assert len(merged.monetary_amounts) == 1 and removed == 1
    assert "people" in merged.not_found


def test_comparison_requires_at_least_two_documents(workspace_with, offline):
    ws = workspace_with(MSA)
    with pytest.raises(WorkflowError):
        compare_documents(ws, offline, ws.doc_ids)


def test_comparison_offline_runs_and_validates(workspace_with, offline):
    ws = workspace_with(MSA, AMENDMENT)
    result = compare_documents(ws, offline, ws.doc_ids)
    assert result.report.unknown_source_ids == []
    assert {p.filename for p in result.sources} == {MSA, AMENDMENT}
    assert result.coverage.complete


# ------------------------------------------------------------------ session handling


def test_workspaces_are_isolated(settings, fixture_bytes):
    alice, bob = DocumentWorkspace(settings), DocumentWorkspace(settings)
    alice.add_pdf(MSA, fixture_bytes(MSA))
    assert bob.documents == [] and bob.search("monthly service fee", 5) == []
    assert alice.search("monthly service fee", 5)


def test_remove_and_clear_documents(workspace_with):
    ws = workspace_with(MSA, AMENDMENT)
    first = ws.doc_ids[0]
    assert ws.remove(first) and first not in ws.doc_ids
    assert all(h.chunk.doc_id != first for h in ws.search("fee", 10))
    ws.clear()
    assert ws.documents == [] and ws.stats()["chunks"] == 0


def test_duplicate_upload_is_detected(workspace_with, fixture_bytes):
    ws = workspace_with(MSA)
    again = ws.add_pdf("copy.pdf", fixture_bytes(MSA))
    assert again.duplicate and len(ws.documents) == 1


def test_document_and_page_limits_are_enforced(settings, fixture_bytes):
    ws = DocumentWorkspace(settings.with_overrides(max_documents=1))
    assert ws.add_pdf(MSA, fixture_bytes(MSA)).ok
    blocked = ws.add_pdf(AMENDMENT, fixture_bytes(AMENDMENT))
    assert not blocked.ok and "limit" in blocked.error.lower()
    ws2 = DocumentWorkspace(settings.with_overrides(max_total_pages=5))
    assert ws2.add_pdf(MSA, fixture_bytes(MSA)).ok  # 4 pages
    assert "exceed" in ws2.add_pdf(AMENDMENT, fixture_bytes(AMENDMENT)).error  # +2 pages > 5


def test_invalid_upload_returns_friendly_error(settings):
    result = DocumentWorkspace(settings).add_pdf("fake.pdf", b"not a pdf")
    assert not result.ok and "not a valid PDF" in result.error
