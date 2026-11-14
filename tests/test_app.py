"""Headless UI tests with Streamlit's AppTest (offline provider; no network or API keys).

Each AppTest instance is an independent browser session, which also lets us check that
documents loaded in one session are not visible in another.
"""

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import MSA, ROOT, SCANNED

APP = str(ROOT / "app.py")
TIMEOUT = 60


@pytest.fixture
def offline_env(monkeypatch):
    monkeypatch.setenv("DOCINTEL_PROVIDER", "mock")


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.run()
    assert not at.exception, at.exception
    return at


def all_text(at: AppTest) -> str:
    parts = []
    for kind in ("markdown", "caption", "info", "warning", "error", "success", "title"):
        parts += [str(getattr(e, "value", "")) for e in getattr(at, kind)]
    return "\n".join(parts)


def button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_app_starts_with_empty_state_and_offline_notice(offline_env):
    at = run_app()
    text = all_text(at)
    assert "DocIntel AI" in text
    assert "Add PDFs in the sidebar" in text
    assert "Offline demo mode" in text
    assert [t.label for t in at.tabs] == [
        "Ask",
        "Summarize",
        "Extract",
        "Compare",
        "Evaluation",
        "About",
    ]


def test_load_samples_and_ask_a_question(offline_env):
    at = run_app()
    button(at, "Load sample documents").click().run()
    assert not at.exception
    assert len(at.session_state.workspace.documents) == 7
    at.chat_input[0].set_value(
        "What is the monthly service fee in the master services agreement?"
    ).run()
    assert not at.exception
    turn = at.session_state.messages[-1]
    assert turn["error"] is None
    result = turn["result"]
    assert result.output.status == "answered" and result.report.unknown_source_ids == []
    assert "Evidence" in all_text(at)


def test_upload_valid_and_invalid_files(offline_env, fixture_bytes):
    at = run_app()
    at.sidebar.file_uploader[0].set_value(
        [
            (MSA, fixture_bytes(MSA), "application/pdf"),
            (SCANNED, fixture_bytes(SCANNED), "application/pdf"),
            ("notes.pdf", b"this is not a pdf", "application/pdf"),
        ]
    ).run()
    assert not at.exception
    names = [r.filename for r in at.session_state.workspace.documents]
    assert names == [MSA]
    errors = " ".join(str(e.value) for e in at.sidebar.error)
    assert "OCR" in errors and "not a valid PDF" in errors


def test_summarize_extract_and_compare_tabs(offline_env):
    at = run_app()
    button(at, "Load sample documents").click().run()
    button(at, "Summarize").click().run()
    assert not at.exception and at.session_state.summary_result is not None
    button(at, "Extract").click().run()
    assert not at.exception and at.session_state.extraction_result is not None
    button(at, "Compare").click().run()
    assert not at.exception and at.session_state.comparison_result is not None


def test_sessions_are_isolated_and_clear_session_works(offline_env):
    first = run_app()
    button(first, "Load sample documents").click().run()
    second = run_app()
    assert second.session_state.workspace.documents == []
    assert len(first.session_state.workspace.documents) == 7
    button(first, "Clear everything").click().run()
    assert not first.exception
    assert first.session_state.workspace.documents == []
    assert first.session_state.messages == []
