"""Bring-your-own-key tests: key format checks, the per-session key store and key precedence.

Every key in this file is a made-up placeholder, and nothing here is sent anywhere.
"""

import pytest

from docintel.config import Settings
from docintel.credentials import (
    KeyFormatError,
    SessionKeyStore,
    check_key_format,
    resolve_credential,
    unsafe_sdk_environment,
)

USER_KEY = "user-session-key-for-tests-0001"
OTHER_USER_KEY = "other-user-key-for-tests-00002"
SERVER_ENV = {
    "OPENAI_API_KEY": "server-env-key-must-not-be-used-0000",
    "ANTHROPIC_API_KEY": "server-env-anthropic-key-00000000",
}
BYOK = Settings()
OWNER = Settings(key_mode="owner")


def store_with(provider: str = "openai", key: str = USER_KEY) -> SessionKeyStore:
    store = SessionKeyStore()
    store.set(provider, key)
    return store


# ------------------------------------------------------------------ precedence


def test_byok_never_falls_back_to_the_server_key():
    assert resolve_credential("openai", BYOK, SessionKeyStore(), server_env=SERVER_ENV) is None
    assert resolve_credential("openai", BYOK, None, server_env=SERVER_ENV) is None


def test_byok_uses_the_sessions_own_key():
    credential = resolve_credential("openai", BYOK, store_with(), server_env=SERVER_ENV)
    assert credential.source == "session" and credential.is_session_key
    assert credential.secret.get_secret_value() == USER_KEY


def test_owner_mode_uses_the_server_key_only_when_explicitly_configured():
    credential = resolve_credential("openai", OWNER, SessionKeyStore(), server_env=SERVER_ENV)
    assert credential.source == "server" and not credential.is_session_key
    assert credential.secret.get_secret_value() == SERVER_ENV["OPENAI_API_KEY"]
    assert resolve_credential("openai", OWNER, SessionKeyStore(), server_env={}) is None


def test_a_sessions_own_key_takes_precedence_over_the_server_key():
    credential = resolve_credential("openai", OWNER, store_with(), server_env=SERVER_ENV)
    assert credential.source == "session"
    assert credential.secret.get_secret_value() == USER_KEY


def test_keys_are_scoped_to_the_provider_they_were_entered_for():
    store = store_with("openai")
    assert resolve_credential("anthropic", BYOK, store, server_env=SERVER_ENV) is None
    assert resolve_credential("gemini", OWNER, store, server_env=SERVER_ENV) is None
    assert resolve_credential("mock", OWNER, store, server_env=SERVER_ENV) is None
    anthropic = resolve_credential("anthropic", OWNER, store, server_env=SERVER_ENV)
    assert anthropic.provider == "anthropic" and anthropic.source == "server"


def test_separate_session_stores_never_share_keys():
    first, second = store_with(key=USER_KEY), store_with(key=OTHER_USER_KEY)
    assert first.get("openai").get_secret_value() == USER_KEY
    assert second.get("openai").get_secret_value() == OTHER_USER_KEY
    first.remove("openai")
    assert "openai" not in first and second.get("openai").get_secret_value() == OTHER_USER_KEY


# ------------------------------------------------------------------ store and removal


def test_store_set_remove_and_clear():
    store = SessionKeyStore()
    store.set("openai", f"  {USER_KEY}\n")  # whitespace picked up by copy-paste is removed
    store.set("anthropic", OTHER_USER_KEY)
    assert store.get("openai").get_secret_value() == USER_KEY
    assert store.providers() == ["anthropic", "openai"]
    assert store.remove("openai") is True and store.remove("openai") is False
    assert store.get("openai") is None and len(store) == 1
    store.clear()
    assert len(store) == 0


def test_keys_never_appear_in_reprs_or_strings():
    store = store_with()
    credential = resolve_credential("openai", BYOK, store)
    shown = (repr(store), str(store), repr(credential), str(credential), str(credential.secret))
    assert all(USER_KEY not in text for text in shown)
    assert "openai" in repr(store)


def test_an_unusable_key_is_not_stored():
    store = SessionKeyStore()
    with pytest.raises(KeyFormatError):
        store.set("openai", "too-short")
    assert "openai" not in store and len(store) == 0


# ------------------------------------------------------------------ format checks


@pytest.mark.parametrize(
    ("provider", "raw", "fragment"),
    [
        ("openai", "", "Paste your OpenAI API key"),
        ("openai", "   ", "Paste your OpenAI API key"),
        ("openai", "short-key", "too short"),
        ("openai", "x" * 600, "too long"),
        ("openai", "has spaces in the middle 1234", "spaces"),
        ("openai", "sk-ant-" + "x" * 16, "Anthropic"),
        ("openai", "AIza" + "x" * 20, "Google"),
        ("anthropic", "sk-proj-" + "x" * 16, "OpenAI"),
        ("anthropic", "AIza" + "x" * 20, "Google"),
        ("gemini", "sk-ant-" + "x" * 16, "Anthropic"),
        ("gemini", "sk-" + "x" * 20, "OpenAI"),
        ("mock", USER_KEY, "Offline"),
    ],
)
def test_unusable_keys_are_refused_without_echoing_them(provider, raw, fragment):
    with pytest.raises(KeyFormatError) as err:
        check_key_format(provider, raw)
    assert fragment in str(err.value)
    assert not raw.strip() or raw.strip() not in str(err.value)


def test_plausible_keys_are_accepted_and_trimmed():
    assert check_key_format("openai", f" {USER_KEY} ") == USER_KEY
    assert check_key_format("openai", "sk-" + "x" * 20) == "sk-" + "x" * 20
    assert check_key_format("anthropic", "sk-ant-" + "x" * 16) == "sk-ant-" + "x" * 16
    assert check_key_format("gemini", "AIza" + "x" * 20) == "AIza" + "x" * 20


# ------------------------------------------------------------------ server SDK variables


def test_sdk_variables_that_cannot_be_overridden_are_reported():
    env = {
        "OPENAI_CUSTOM_HEADERS": "X-Team: ops",
        "OPENAI_LOG": "debug",
        "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE": "metadata",
    }
    assert unsafe_sdk_environment("openai", env) == ["OPENAI_CUSTOM_HEADERS", "OPENAI_LOG"]
    assert unsafe_sdk_environment("anthropic", env) == []  # traces without content are fine
    env["ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE"] = "content"
    assert unsafe_sdk_environment("anthropic", env) == [
        "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE"
    ]
    assert unsafe_sdk_environment("gemini", env) == []
    assert unsafe_sdk_environment("openai", {"OPENAI_LOG": "  "}) == []
