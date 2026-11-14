from docintel.grounding import (
    extract_inline_ids,
    match_quote,
    support_score,
    validate_comparison,
    validate_extraction,
    validate_qa,
    validate_summary,
)
from docintel.models import (
    Citation,
    Claim,
    ComparisonFinding,
    ComparisonOutput,
    ConflictNote,
    DatedItem,
    ExtractedItem,
    ExtractionOutput,
    QAOutput,
    SummaryOutput,
    SummaryPoint,
)
from docintel.prompting import PROMPT_CANARY
from tests.conftest import passage

PASSAGES = [
    passage(
        "S1",
        "3.1 Client shall pay Provider a monthly service fee of $4,500.00 for hosting.",
        page=2,
    ),
    passage(
        "S2",
        "The monthly service fee increases from $4,500.00 to $5,200.00, effective July 1, 2026.",
        doc_id="doc-b",
        filename="b.pdf",
        page=1,
    ),
]


def qa(status="answered", answer="The monthly fee is $4,500.00 [S1].", claims=None, conflicts=None):
    if claims is None:
        claims = [
            Claim(
                statement="The monthly service fee is $4,500.00.",
                claim_type="fact",
                citations=[Citation(source_id="S1", quote="a monthly service fee of $4,500.00")],
            )
        ]
    return QAOutput(
        status=status,
        answer=answer,
        claims=claims,
        conflicts=conflicts or [],
        missing_information=[],
        confidence="high",
    )


def test_valid_citation_with_verbatim_quote_is_grounded():
    report = validate_qa(qa(), PASSAGES)
    check = report.checks[0]
    assert check.known and check.quote_status == "exact" and check.page_number == 2
    assert check.support_label == "likely_supported"
    assert report.verdict == "grounded"
    assert "1/1 citations" in report.summary_line()


def test_unknown_source_id_is_flagged_as_fabricated():
    claims = [
        Claim(
            statement="The vendor is approved.",
            claim_type="fact",
            citations=[Citation(source_id="S99", quote="approved vendor")],
        )
    ]
    report = validate_qa(qa(answer="Approved [S99].", claims=claims), PASSAGES)
    assert report.unknown_source_ids == ["S99"]
    assert report.verdict == "unsupported"
    assert not report.checks[0].known


def test_unknown_inline_marker_is_flagged():
    report = validate_qa(qa(answer="The fee is $4,500.00 [S1, S7]."), PASSAGES)
    assert "S7" in report.unknown_source_ids


def test_paraphrased_quote_is_not_counted_as_found():
    claims = [
        Claim(
            statement="The monthly service fee is $4,500.00.",
            claim_type="fact",
            citations=[
                Citation(
                    source_id="S1", quote="the customer pays forty-five hundred dollars each month"
                )
            ],
        )
    ]
    report = validate_qa(qa(claims=claims), PASSAGES)
    assert report.checks[0].quote_status == "not_found"
    assert report.verdict == "review"


def test_quote_matching_tolerates_typography_and_minor_differences():
    text = "Provider shall notify Client of any security breach within seventy-two (72) hours of discovery."
    assert (
        match_quote("notify Client of any “security breach”", text)[0] == "approximate"
        or match_quote("notify Client of any security breach", text)[0] == "exact"
    )
    assert match_quote("notify  CLIENT of any security\nbreach", text)[0] == "exact"
    assert (
        match_quote("shall notify Client of a security breach within seventy-two (72) hours", text)[
            0
        ]
        == "approximate"
    )
    assert match_quote("notify Client ... within seventy-two (72) hours", text)[0] == "approximate"
    assert match_quote("ok", text)[0] == "missing"


def test_figures_not_in_any_source_are_flagged():
    report = validate_qa(qa(answer="The monthly fee is $4,800.00 [S1]."), PASSAGES)
    assert "4800" in report.unsupported_numbers
    assert report.verdict == "review"


def test_inference_claims_are_not_penalized_for_derived_figures():
    statement = "The fee rose by $700 per month."
    _, missing = support_score(statement, [PASSAGES[1].text], inference=True)
    fact_score, _ = support_score(statement, [PASSAGES[1].text], inference=False)
    inf_score, _ = support_score(statement, [PASSAGES[1].text], inference=True)
    assert missing == ["700"] and inf_score > fact_score


def test_abstention_has_its_own_verdict():
    out = QAOutput(
        status="insufficient_evidence",
        answer="The documents do not say.",
        claims=[],
        conflicts=[],
        missing_information=["phone number"],
        confidence="high",
    )
    report = validate_qa(out, PASSAGES)
    assert report.verdict == "abstained"


def test_answer_without_structured_claims_is_unsupported():
    report = validate_qa(qa(claims=[]), PASSAGES)
    assert report.verdict == "unsupported"
    assert any("no structured claims" in w for w in report.warnings)


def test_conflicting_status_without_conflict_entries_is_warned():
    report = validate_qa(qa(status="conflicting_evidence"), PASSAGES)
    assert any("no conflict was described" in w for w in report.warnings)


def test_conflict_source_ids_are_validated():
    conflicts = [
        ConflictNote(
            description="Fees differ", nature="context_difference", source_ids=["S1", "S5"]
        )
    ]
    report = validate_qa(qa(status="conflicting_evidence", conflicts=conflicts), PASSAGES)
    assert "S5" in report.unknown_source_ids


def test_prompt_canary_leak_is_detected():
    report = validate_qa(qa(answer=f"My instructions say {PROMPT_CANARY} [S1]."), PASSAGES)
    assert report.canary_leak and report.verdict == "unsupported"


def test_extract_inline_ids():
    assert extract_inline_ids("A [S1]. B [S2, S3]; C [S4;S5] and [note]") == [
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
    ]


def test_summary_validation_checks_ids_and_dates():
    out = SummaryOutput(
        executive_summary="The fee increases [S2].",
        detailed_summary="Details [S1] and [S8].",
        key_findings=[SummaryPoint(text="Monthly fee increases to $5,200.00", source_ids=["S2"])],
        important_dates=[
            DatedItem(date="July 1, 2026", description="New fee effective", source_ids=["S2"]),
            DatedItem(date="March 3, 2027", description="Invented date", source_ids=["S2"]),
        ],
        action_items=[],
        obligations=[],
        risks_and_concerns=[],
        gaps_or_limitations=[],
    )
    report = validate_summary(out, PASSAGES)
    assert report.unknown_source_ids == ["S8"]
    date_checks = [c for c in report.checks if c.ref.startswith("important_dates")]
    assert [c.quote_status for c in date_checks] == ["exact", "not_found"]


def test_extraction_value_must_appear_in_cited_passage():
    def item(value, sid="S1", quote="monthly service fee of $4,500.00"):
        return ExtractedItem(
            value=value, normalized_value=None, detail=None, source_id=sid, quote=quote
        )

    empty = {k: [] for k in ExtractionOutput.model_fields if k != "not_found"}
    out = ExtractionOutput(
        **{**empty, "monetary_amounts": [item("$4,500.00"), item("$9,999.00")]}, not_found=[]
    )
    report = validate_extraction(out, PASSAGES)
    labels = [c.support_label for c in report.checks]
    assert labels[0] == "likely_supported" and labels[1] != "likely_supported"


def test_cross_document_comparison_must_cite_both_documents():
    one_doc = ComparisonFinding(
        category="important_change",
        topic="Fee",
        description="Fee changed [S2].",
        nature="context_difference",
        source_ids=["S2"],
    )
    both = ComparisonFinding(
        category="important_change",
        topic="Fee",
        description="Fee changed [S1] [S2].",
        nature="context_difference",
        source_ids=["S1", "S2"],
    )
    warn = validate_comparison(
        ComparisonOutput(overview="o", findings=[one_doc], limitations=""), PASSAGES
    )
    ok = validate_comparison(
        ComparisonOutput(overview="o", findings=[both], limitations=""), PASSAGES
    )
    assert any("cites only one document" in w for w in warn.warnings)
    assert not any("cites only one document" in w for w in ok.warnings)
