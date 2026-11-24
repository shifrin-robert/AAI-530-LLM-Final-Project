"""The human-review worksheet: every case, automatic columns filled, reviewer columns blank."""

import csv
import json

import pytest

from evaluation import make_review_sheet as sheet

RESULTS = sheet.HERE / "results"
OFFLINE_RUN = next(RESULTS.glob("*_offline_extractive-baseline_*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_blank_template_has_every_case_and_no_answers():
    rows = sheet.build_rows(None)
    assert len(rows) == 40 and list(rows[0]) == sheet.COLUMNS
    assert {r["Test ID"] for r in rows} == {
        c["id"] for c in load(sheet.HERE / "test_cases.json")["cases"]
    }
    assert all(not r["Actual response"] and not r["Automatic score"] for r in rows)


def test_prefilled_sheet_copies_the_run_and_leaves_reviewer_columns_blank():
    run = load(OFFLINE_RUN)
    rows = sheet.build_rows(run, repeats=run)
    by_id = {r["case_id"]: r for r in run["results"]}
    for row in rows:
        record = by_id[row["Test ID"]]
        assert row["Automatic score"].startswith("PASS" if record["score"]["pass"] else "FAIL")
        assert row["Actual response"] and row["Run ID"] == run["metadata"]["run_id"]
        assert row["Automatic outcome in repeated run"] in {"PASS", "FAIL"}
        assert all(row[column] == "" for column in sheet.REVIEWER_COLUMNS)


def test_failed_checks_are_spelled_out():
    run = load(OFFLINE_RUN)
    rows = {r["Test ID"]: r for r in sheet.build_rows(run)}
    assert (
        rows["INJ-02"]["Automatic score"] == "FAIL (forbidden phrase is the only approved vendor)"
    )
    assert "missing" in rows["CF-01"]["Automatic score"]
    assert "not a semantic check" in rows["DF-01"]["Automatic citation checks"]


def test_cli_writes_a_csv_excel_can_read_without_touching_the_run(tmp_path):
    before = OFFLINE_RUN.read_bytes()
    out = tmp_path / "review.csv"
    assert sheet.main([str(OFFLINE_RUN), "--out", str(out)]) == 0
    assert OFFLINE_RUN.read_bytes() == before
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")  # UTF-8 byte order mark for Excel
    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40 and list(rows[0]) == sheet.COLUMNS


def test_committed_live_worksheet_is_unreviewed_and_matches_its_runs():
    path = sheet.REVIEW_DIR / "20261114T203837Z_openai_gpt-6-luna_v2_live-v2_human_review.csv"
    runs = [
        RESULTS / "20261114T203837Z_openai_gpt-6-luna_v2_live-v2.json",
        RESULTS / "20261114T205255Z_openai_gpt-6-luna_v2_live-v2-x3.json",
    ]
    if not path.is_file() or not all(p.is_file() for p in runs):
        pytest.skip("live worksheet or result files are not present")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        saved = list(csv.DictReader(handle))
    assert saved == sheet.build_rows(load(runs[0]), load(runs[1]))
    assert all(row[c] == "" for row in saved for c in sheet.REVIEWER_COLUMNS)
