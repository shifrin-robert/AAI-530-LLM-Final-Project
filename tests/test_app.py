"""Headless UI tests with Streamlit's AppTest (offline provider; no network or API keys).

Each AppTest instance is an independent browser session, which also lets us check that
documents loaded in one session are not visible in another.
"""

import os
import sys

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


# ------------------------------------------------------------------ bring your own key
# Fake keys only. OPENAI_BASE_URL points at a closed local port, so if a key ever slipped through
# to a real request, the request would fail on this machine instead of reaching a provider.

SERVER_KEY = "server-env-key-must-not-be-used-0000"
USER_KEY = "user-session-key-for-tests-0001"


@pytest.fixture
def openai_selected(monkeypatch):
    monkeypatch.setenv("DOCINTEL_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")


@pytest.fixture
def server_has_key(monkeypatch, openai_selected):
    """A server whose environment holds the developer's own key, as on a laptop."""
    monkeypatch.setenv("OPENAI_API_KEY", SERVER_KEY)


def everything_shown(at: AppTest) -> str:
    """All rendered text plus every widget value, to prove a key is never displayed."""
    values = [str(getattr(w, "value", "")) for w in at.text_input]
    return all_text(at) + "\n" + "\n".join(values)


def enter_key(at: AppTest, key: str, provider: str = "openai") -> AppTest:
    at.text_input(key=f"key_input_{provider}").input(key)
    at.button(key=f"key_submit_{provider}").click().run()
    assert not at.exception, at.exception
    return at


def session_provider(at: AppTest):
    providers = [p for p, _reason in at.session_state.providers.values()]
    assert providers, "no provider was built"
    return providers[-1]


def test_byok_never_uses_the_servers_key(server_has_key):
    at = run_app()
    provider = session_provider(at)
    assert provider.is_offline and len(at.session_state.api_keys) == 0
    text = everything_shown(at)
    assert "Enter your OpenAI API key above" in text and "Offline demo mode" in text
    assert SERVER_KEY not in text
    assert at.text_input(key="key_input_openai").value == ""


def test_a_users_key_is_used_for_their_session_only_and_never_shown(openai_selected):
    at = enter_key(run_app(), USER_KEY)
    provider = session_provider(at)
    assert provider.provider_name == "openai" and not provider.is_offline
    assert provider.client.api_key == USER_KEY  # the SDK client holds this user's key
    assert at.session_state.api_keys.providers() == ["openai"]
    text = everything_shown(at)
    assert "your OpenAI key" in text and "Active model: OpenAI" in text
    assert USER_KEY not in text
    assert "key_input_openai" not in at.session_state or not at.session_state["key_input_openai"]
    assert USER_KEY not in os.environ.values()


def test_removing_the_key_drops_it_and_the_client_that_held_it(openai_selected):
    at = enter_key(run_app(), USER_KEY)
    at.button(key="remove_key_openai").click().run()
    assert not at.exception
    assert len(at.session_state.api_keys) == 0
    assert session_provider(at).is_offline
    assert all(p.is_offline for p, _ in at.session_state.providers.values())
    assert "OpenAI key was removed" in all_text(at)


def test_keys_are_isolated_between_sessions_and_never_global(openai_selected):
    first = enter_key(run_app(), USER_KEY)
    second = run_app()
    assert len(second.session_state.api_keys) == 0
    assert session_provider(second).is_offline
    assert USER_KEY not in everything_shown(second)
    assert session_provider(first).client.api_key == USER_KEY
    assert USER_KEY not in os.environ.values()
    for name, module in list(sys.modules.items()):
        if name == "docintel" or name.startswith("docintel."):
            assert not [v for v in vars(module).values() if USER_KEY in repr(v)], name


def test_owner_mode_uses_the_server_key_and_a_users_own_key_takes_precedence(
    server_has_key, monkeypatch
):
    monkeypatch.setenv("DOCINTEL_KEY_MODE", "owner")
    at = run_app()
    provider = session_provider(at)
    assert not provider.is_offline and provider.client.api_key == SERVER_KEY
    text = everything_shown(at)
    assert "the server's OpenAI key" in text and "Owner mode" in text
    assert SERVER_KEY not in text
    enter_key(at, USER_KEY)
    assert session_provider(at).client.api_key == USER_KEY


def test_key_check_reports_success_and_rejection(openai_selected, monkeypatch):
    from docintel import llm_client

    monkeypatch.setattr(llm_client.OpenAIProvider, "check_access", lambda self: None)
    at = enter_key(run_app(), USER_KEY)
    at.button(key="check_key_openai").click().run()
    assert "OpenAI accepted the key" in all_text(at)

    def rejected(self):
        raise llm_client.LLMAuthenticationError(llm_client._rejected_key_message("OpenAI"))

    monkeypatch.setattr(llm_client.OpenAIProvider, "check_access", rejected)
    at.button(key="check_key_openai").click().run()
    assert "rejected the API key. It may be mistyped, revoked or expired." in all_text(at)
    assert USER_KEY not in everything_shown(at)


def test_a_key_for_another_provider_is_refused_without_being_shown(openai_selected):
    wrong = "sk-ant-" + "x" * 20
    at = enter_key(run_app(), wrong)
    assert len(at.session_state.api_keys) == 0
    text = everything_shown(at)
    assert "looks like an Anthropic key" in text and wrong not in text
    # The form is still shown, and the refused key must not stay in its field or widget state.
    assert at.text_input(key="key_input_openai").value == ""
    assert at.session_state["key_input_openai"] == ""


def test_clear_session_also_removes_keys(openai_selected):
    at = enter_key(run_app(), USER_KEY)
    button(at, "Load sample documents").click().run()
    button(at, "Clear everything").click().run()
    assert not at.exception
    assert len(at.session_state.api_keys) == 0 and session_provider(at).is_offline


def test_session_keys_are_refused_when_the_server_sets_unsafe_sdk_variables(
    openai_selected, monkeypatch
):
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "X-Operator: yes")
    at = enter_key(run_app(), USER_KEY)
    assert session_provider(at).is_offline
    assert "OPENAI_CUSTOM_HEADERS" in all_text(at) and USER_KEY not in everything_shown(at)
