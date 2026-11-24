"""The report figures identify each saved run by prompt version and repeats, never by position."""

import pytest

from evaluation import make_report_charts as charts


def run(prompt="v2", repeats=1, offline=False, run_id="r"):
    return {"offline": offline, "prompt_version": prompt, "repeats": repeats, "run_id": run_id}


def test_runs_are_named_by_prompt_and_repeats():
    assert charts.run_key(run(offline=True)) == "offline"
    assert charts.run_key(run("v1")) == "v1"
    assert charts.run_key(run("v2")) == "v2"
    assert charts.run_key(run("v2", 3)) == "v2x3"
    assert charts.run_key(run("v3", 3)) == "v3x3"


def test_two_runs_with_the_same_name_are_refused(monkeypatch):
    runs = [
        run(offline=True, run_id="a"),
        run("v1"),
        run("v2"),
        run("v2", 3),
        run("v2", 3, run_id="b"),
    ]
    monkeypatch.setattr(
        charts.scoring_audit, "build_audit", lambda *a, **k: {"runs": runs}, raising=True
    )
    with pytest.raises(SystemExit, match="v2x3"):
        charts.load_audit()


def test_saved_runs_are_labelled_with_their_own_prompt():
    try:
        audit = charts.load_audit()
    except SystemExit:
        pytest.skip("saved live runs are not present")
    if "v3x3" not in audit:
        pytest.skip("the prompt v3 run is not present")
    assert audit["v2x3"]["prompt_version"] == "v2" and audit["v3x3"]["prompt_version"] == "v3"
    grid = charts.outcome_grid(audit)
    assert "Prompt v2, repeat 1: 38 of 40" in grid and "Prompt v3, repeat 1: 39 of 40" in grid
    assert "9 runs in rows" in grid
