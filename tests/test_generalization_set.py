"""The generalization set (evaluation/generalization/): separate, well-formed and answerable.

These tests check the dataset, not any model: every reference fact is on its stated page, every
required value reaches the model's context, and the harness runs end to end offline. No model
output is generated or scored here except by the offline extractive baseline, and only to check
that the pipeline runs.
"""

import json

import pytest

from docintel.config import FIXTURES_DIR, Settings
from docintel.pdf_processing import extract_document
from evaluation import evaluation_runner, scoring, scoring_audit
from evaluation.build_generalization_fixtures import (
    DOCUMENTS,
    GENERALIZATION_FIXTURES_DIR,
    build_text_pdf,
)

GEN = json.loads((scoring_audit.GENERALIZATION_DIR / "cases.json").read_text(encoding="utf-8"))
CASES = GEN["cases"]
RELATIONSHIPS = json.loads(
    (scoring_audit.GENERALIZATION_DIR / "relationships.json").read_text(encoding="utf-8")
)
BENCHMARK = json.loads(scoring_audit.CASES_PATH.read_text(encoding="utf-8"))
TYPE_TO_RELATIONSHIP = {
    "dated_values": "different_context",
    "current_vs_historical": "superseded",
    "revised_budget": "superseded",
    "compatible_figures": "compatible",
    "contradiction": "unresolved_contradiction",
}


@pytest.fixture(scope="module")
def page_text():
    settings = Settings(provider="mock")
    cache = {}

    def _get(document: str, page: int) -> str:
        if document not in cache:
            data = (GENERALIZATION_FIXTURES_DIR / document).read_bytes()
            cache[document] = extract_document(document, data, settings)
        return cache[document].pages[page - 1].text

    return _get


def test_the_set_is_separate_from_the_benchmark():
    benchmark_ids = {c["id"] for c in BENCHMARK["cases"]}
    benchmark_docs = {d for c in BENCHMARK["cases"] for d in c["documents"]}
    assert GEN["dataset_version"] != BENCHMARK["dataset_version"]
    assert all(c["id"].startswith("GEN-") and c["id"] not in benchmark_ids for c in CASES)
    for case in CASES:
        for name in case["documents"]:
            assert name in DOCUMENTS and name not in benchmark_docs
            assert (GENERALIZATION_FIXTURES_DIR / name).is_file()
            assert not (FIXTURES_DIR / name).exists()  # nothing added to the benchmark folder


def test_two_cases_for_each_situation_with_matching_annotations():
    types = [c["generalization_type"] for c in CASES]
    assert sorted(set(types)) == sorted(TYPE_TO_RELATIONSHIP) and len(CASES) == 10
    assert all(types.count(t) == 2 for t in TYPE_TO_RELATIONSHIP)
    assert set(RELATIONSHIPS["cases"]) == {c["id"] for c in CASES}
    for case in CASES:
        annotation = RELATIONSHIPS["cases"][case["id"]]
        assert annotation["relationship"] == TYPE_TO_RELATIONSHIP[case["generalization_type"]]
        assert case["reference_verified_by_human"] is False
        assert case["criteria"] and case["question"] and case["expected"]["evidence"]


def test_date_markers_accept_month_first_and_day_first_dates():
    for annotation in RELATIONSHIPS["cases"].values():
        for group in annotation.get("context_markers", []):
            assert any(m[0].isalpha() for m in group) and any(m[0].isdigit() for m in group)
            assert any(m.split()[0].isdigit() for m in group if " " in m)  # "31 march"


def test_required_facts_appear_on_expected_evidence_pages(page_text):
    for case in CASES:
        evidence = " ".join(
            page_text(e["document"], e["page"]) for e in case["expected"]["evidence"]
        )
        for group in case["expected"]["required_facts"]:
            assert scoring.group_matches(evidence, group), f"{case['id']}: {group}"


def test_contradictions_are_about_the_same_fact_and_dated_values_differ_in_date(page_text):
    meadowbrook = [page_text(d, 2) for d in ("meadowbrook_renovation_report_q1_2026.pdf",
                                               "meadowbrook_board_memo_may_2026.pdf")]  # fmt: skip
    assert all("awarded on February 2, 2026" in text for text in meadowbrook)
    harlow = page_text("harlow_arts_council_chair_letter_2026.pdf", 1)
    assert "year ended December 31, 2025" in harlow


def test_committed_pdfs_match_the_generator():
    settings = Settings(provider="mock")
    for name, spec in DOCUMENTS.items():
        regenerated = extract_document(name, build_text_pdf(spec), settings)
        committed = extract_document(
            name, (GENERALIZATION_FIXTURES_DIR / name).read_bytes(), settings
        )
        assert [p.text for p in regenerated.pages] == [p.text for p in committed.pages], name


def test_every_required_value_reaches_the_models_context():
    """Retrieval is not the bottleneck: each case tests the answer, not the search."""
    settings_like = {"retriever": "hybrid", "prompt_version": "v2"}
    for case in CASES:
        check = scoring_audit.context_check(case, settings_like, GENERALIZATION_FIXTURES_DIR)
        assert check["all_values_in_context"], (case["id"], check["values"])


def test_documents_contain_no_prompt_example_values():
    texts = " ".join(" ".join(spec["pages"]) for spec in DOCUMENTS.values())
    for value in ("$52,000", "$40,000", "15 August", "30 June"):  # prompt v3's example
        assert value not in texts


def test_offline_runner_and_audit_handle_the_set(tmp_path):
    out = tmp_path / "runs"
    code = evaluation_runner.main(
        ["--provider", "mock", "--dataset", "generalization", "--out", str(out)]
    )
    assert code == 0
    run_file = next(out.glob("*.json"))
    run = json.loads(run_file.read_text(encoding="utf-8"))
    assert run["metadata"]["dataset_version"] == "generalization-1.0.0"
    assert run["metadata"]["case_count"] == 10 and run["metrics"]["errors"] == 0
    audit = scoring_audit.build_audit(
        [run_file], with_context_check=False, dataset="generalization"
    )
    entry = audit["runs"][0]
    assert entry["original_scores_reproduced"]
    assert len([r for r in entry["rows"] if "relationship" in r]) == 10


def test_audit_reports_when_no_generalization_runs_exist(tmp_path, capsys, monkeypatch):
    empty = tmp_path / "results"
    empty.mkdir()
    dataset = scoring_audit.DATASETS["generalization"]
    monkeypatch.setitem(
        scoring_audit.DATASETS,
        "generalization",
        scoring_audit.Dataset(
            dataset.cases,
            dataset.relationships,
            dataset.fixtures,
            empty,
            tmp_path / "audit",
            (),
        ),
    )
    assert scoring_audit.main(["--dataset", "generalization"]) == 0
    assert "No saved runs" in capsys.readouterr().out
    assert not (tmp_path / "audit").exists()
