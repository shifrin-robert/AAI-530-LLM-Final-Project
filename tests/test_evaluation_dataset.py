"""Integrity checks for the evaluation dataset and scoring code.

The most important check: every reference fact in test_cases.json must actually appear on the
evidence page(s) the case names, in the real extracted fixture text. This keeps the labelled
answers human-verifiable and stops AI-drafted reference answers from silently drifting.
"""

import json
import re
from collections import Counter

import pytest
from pydantic import SecretStr

from docintel.config import FIXTURES_DIR, Settings
from docintel.credentials import Credential
from docintel.llm_client import LLMQuotaError, ProviderStatus, ScriptedProvider
from docintel.pdf_processing import extract_document
from evaluation import evaluation_runner, scoring
from evaluation.build_fixtures import DOCUMENTS, build_text_pdf
from tests.conftest import ROOT

CASES = json.loads((ROOT / "evaluation" / "test_cases.json").read_text())["cases"]
PARAPHRASE = json.loads((ROOT / "evaluation" / "retrieval_paraphrase_cases.json").read_text())[
    "cases"
]
REQUIRED_FIELDS = {
    "id",
    "category",
    "task",
    "documents",
    "expected",
    "criteria",
    "evaluation_method",
    "notes",
    "reference_verified_by_human",
}


@pytest.fixture(scope="module")
def page_text():
    settings = Settings(provider="mock")
    cache = {}

    def _get(document: str, page: int) -> str:
        if document not in cache:
            cache[document] = extract_document(
                document, (FIXTURES_DIR / document).read_bytes(), settings
            )
        return cache[document].pages[page - 1].text

    return _get


def test_dataset_shape():
    assert 30 <= len(CASES) <= 45
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert set(case) >= REQUIRED_FIELDS, case["id"]
        assert case["task"] in {"qa", "summary", "extraction", "comparison"}
        if case["task"] == "qa":
            assert case["question"].strip()
    categories = Counter(c["category"] for c in CASES)
    for needed in (
        "direct_factual",
        "multi_page",
        "multi_document",
        "numerical",
        "missing_information",
        "conflicting_evidence",
        "prompt_injection",
        "ambiguous",
        "summarization",
        "extraction",
        "comparison",
    ):
        assert categories[needed] >= 2, needed


def test_case_documents_exist():
    for case in CASES:
        for name in case["documents"]:
            assert (FIXTURES_DIR / name).is_file(), f"{case['id']}: missing fixture {name}"


def test_required_facts_appear_on_expected_evidence_pages(page_text):
    for case in CASES:
        expected = case["expected"]
        evidence = expected.get("evidence", [])
        if (
            case["task"] not in {"qa", "summary", "comparison"}
            or not expected.get("required_facts")
            or not evidence
        ):
            continue
        documents_text = " ".join(
            page_text(name, i + 1)
            for name in case["documents"]
            for i in range(len(DOCUMENTS[name]["pages"]))
        )
        evidence_text = " ".join(page_text(e["document"], e["page"]) for e in evidence)
        for group in expected["required_facts"]:
            if case["task"] == "qa":
                assert scoring.group_matches(evidence_text, group), (
                    f"{case['id']}: {group} not on evidence pages"
                )
            else:
                assert scoring.group_matches(documents_text, group), (
                    f"{case['id']}: {group} not in documents"
                )


def test_missing_information_cases_have_no_answer_in_documents(page_text):
    forbidden_hits = []
    for case in CASES:
        if case["category"] != "missing_information":
            continue
        text = " ".join(
            page_text(n, i + 1)
            for n in case["documents"]
            for i in range(len(DOCUMENTS[n]["pages"]))
        )
        forbidden_hits += [
            p for p in case["expected"].get("forbidden_phrases", []) if p.lower() in text.lower()
        ]
    assert forbidden_hits == []


def test_extraction_expected_items_exist_in_documents(page_text):
    for case in CASES:
        if case["task"] != "extraction":
            continue
        text = " ".join(
            page_text(n, i + 1)
            for n in case["documents"]
            for i in range(len(DOCUMENTS[n]["pages"]))
        )
        for values in case["expected"]["items"].values():
            for value in values:
                assert scoring.normalize(value) in scoring.normalize(text), f"{case['id']}: {value}"


def test_paraphrase_cases_point_to_pages_containing_the_source_wording(page_text):
    for case in PARAPHRASE:
        evidence_text = " ".join(page_text(e["document"], e["page"]) for e in case["evidence"])
        for fragment in re.split(r"\s*\.\.\.\s*", case["source_wording"]):
            assert scoring.normalize(fragment) in scoring.normalize(evidence_text), (
                f"{case['id']}: {fragment}"
            )


def test_committed_fixtures_match_the_generator(settings_text=None):
    settings = Settings(provider="mock")
    for name, spec in DOCUMENTS.items():
        regenerated = extract_document(name, build_text_pdf(spec), settings)
        committed = extract_document(name, (FIXTURES_DIR / name).read_bytes(), settings)
        assert [p.text for p in regenerated.pages] == [p.text for p in committed.pages], name


def test_scoring_fact_matching_rules():
    assert scoring.group_matches("The fee is $4500.00 per month", ["4,500"])
    assert scoring.group_matches("Sixty days' notice", ["60", "sixty"])
    assert not scoring.group_matches("The fee is $4,800", ["4,500"])
    matched, total, missing = scoring.score_facts(
        "Amber status, 85% done", [["amber"], ["85%"], ["6,500"]]
    )
    assert (matched, total, missing) == (2, 3, [["6,500"]])
    assert scoring.forbidden_hits("He is the ONLY approved vendor", ["only approved vendor"]) == [
        "only approved vendor"
    ]


def test_offline_evaluation_runner_end_to_end(tmp_path):
    code = evaluation_runner.main(
        [
            "--provider",
            "mock",
            "--cases",
            "DF-01,MI-02,INJ-01,SUM-01,EXT-01,CMP-01",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 0
    runs = list(tmp_path.glob("*.json"))
    assert len(runs) == 1
    run = json.loads(runs[0].read_text())
    assert run["metadata"]["offline"] is True and run["metadata"]["case_count"] == 6
    assert run["metrics"]["errors"] == 0 and run["metrics"]["format_compliance"] == 1.0
    assert (tmp_path / f"{run['metadata']['run_id']}.md").is_file()


@pytest.mark.parametrize("version", [None, "v1", "v2", "v3"])
def test_offline_runner_defaults_to_v3_and_still_runs_v1_and_v2(tmp_path, version):
    flags = [] if version is None else ["--prompt-version", version]
    code = evaluation_runner.main(
        ["--provider", "mock", "--cases", "CF-02", "--out", str(tmp_path), *flags]
    )
    assert code == 0
    run = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert run["metadata"]["prompt_version"] == (version or "v3")
    assert run["metrics"]["errors"] == 0


def test_runner_refuses_paid_provider_without_explicit_permission(tmp_path, capsys):
    code = evaluation_runner.main(
        ["--provider", "openai", "--cases", "DF-01", "--out", str(tmp_path)]
    )
    assert code == 2
    assert "--allow-paid" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.json"))


def test_runner_dry_run_prices_each_case_separately(tmp_path, capsys):
    """Haiku 5.5 and gpt-6-luna share base prices; pricing all 40 cases as one request would
    wrongly apply Haiku's 5x long-prompt tier."""
    for provider in ("openai", "anthropic"):
        assert evaluation_runner.main(["--provider", provider, "--out", str(tmp_path)]) == 2
    out = capsys.readouterr().out.splitlines()
    estimates = [line.split("estimate ")[1] for line in out if line.startswith("Planned")]
    assert estimates == ["$0.0540.", "$0.0540."]


def test_runner_reports_a_missing_key_without_starting(tmp_path, capsys):
    code = evaluation_runner.main(
        ["--provider", "openai", "--allow-paid", "--cases", "DF-01", "--out", str(tmp_path)]
    )
    assert code == 2
    assert "Cannot start: OPENAI_API_KEY is not set" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_runner_stops_on_a_spend_limit_without_writing_results(tmp_path, monkeypatch, capsys):
    provider = ScriptedProvider([LLMQuotaError("Spend limit reached.")])
    fake = Credential("openai", SecretStr("runner-test-key-not-a-real-key-00"), "server")
    monkeypatch.setattr(evaluation_runner, "server_credential", lambda name: fake)
    monkeypatch.setattr(
        evaluation_runner,
        "create_provider",
        lambda settings, credential=None: ProviderStatus(provider, "openai"),
    )
    code = evaluation_runner.main(
        ["--provider", "openai", "--allow-paid", "--cases", "DF-01,DF-02", "--out", str(tmp_path)]
    )
    assert code == evaluation_runner.EXIT_STOPPED
    assert len(provider.requests) == 1  # DF-02 was never sent
    assert "no results file was written" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_runner_uses_the_owners_server_key_and_never_writes_it(tmp_path, monkeypatch, capsys):
    """The command-line runner is the key owner's own tool: it passes the server key explicitly,
    and no key value appears in the result files it writes."""
    from docintel.offline_provider import ExtractiveOfflineProvider

    owner_key = "runner-owner-key-not-a-real-key-01"
    monkeypatch.setenv("OPENAI_API_KEY", owner_key)
    used = []

    def fake_create_provider(settings, credential=None):
        used.append(credential)
        return ProviderStatus(ExtractiveOfflineProvider(settings), "openai")

    monkeypatch.setattr(evaluation_runner, "create_provider", fake_create_provider)
    code = evaluation_runner.main(
        ["--provider", "openai", "--allow-paid", "--cases", "DF-01", "--out", str(tmp_path)]
    )
    assert code == 0
    assert [(c.provider, c.source) for c in used] == [("openai", "server")]
    assert used[0].secret.get_secret_value() == owner_key
    written = [p.read_text(encoding="utf-8") for p in tmp_path.iterdir()]
    assert written and all(owner_key not in text for text in written)
    assert owner_key not in capsys.readouterr().out
