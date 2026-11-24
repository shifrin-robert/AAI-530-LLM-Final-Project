import os

import pytest

from docintel import config
from docintel.config import ConfigError, Settings, read_dotenv, server_api_key
from docintel.model_catalog import CATALOG, DEFAULT_MODEL_BY_PROVIDER, get_model_info

PLACEHOLDER = "placeholder-value-must-not-load"


def test_test_suite_never_loads_a_real_env_file(tmp_path, monkeypatch):
    """A key in .env (needed for live evaluation) must never reach the offline test suite."""
    (tmp_path / ".env").write_text(
        f"OPENAI_API_KEY={PLACEHOLDER}\nDOCINTEL_TOP_K=3\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    try:
        settings = Settings.from_env()
        assert server_api_key("openai") is None
        assert settings.top_k == Settings().top_k
    finally:
        os.environ.pop("OPENAI_API_KEY", None)  # only reached if the conftest guard regresses


def test_reading_dotenv_never_copies_values_into_the_process_environment(tmp_path):
    """SDKs read os.environ on their own, so .env keys must never be copied there."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={PLACEHOLDER}\nDOCINTEL_KEY_MODE=owner\n")
    before = dict(os.environ)
    assert read_dotenv(env_file) == {"OPENAI_API_KEY": PLACEHOLDER, "DOCINTEL_KEY_MODE": "owner"}
    assert dict(os.environ) == before and PLACEHOLDER not in os.environ.values()


def test_key_mode_defaults_to_byok_and_owner_mode_must_be_explicit():
    assert Settings().key_mode == "byok"
    assert Settings.from_env({}).key_mode == "byok"
    assert Settings.from_env({"DOCINTEL_KEY_MODE": " Owner "}).key_mode == "owner"
    with pytest.raises(ConfigError, match="DOCINTEL_KEY_MODE"):
        Settings.from_env({"DOCINTEL_KEY_MODE": "shared"})


def test_server_settings_prefer_real_environment_over_dotenv(monkeypatch):
    monkeypatch.setattr(config, "_dotenv_values", lambda: {"DOCINTEL_TOP_K": "3"})
    assert Settings.from_env().top_k == 3
    monkeypatch.setenv("DOCINTEL_TOP_K", "5")
    assert Settings.from_env().top_k == 5


def test_defaults_are_valid():
    s = Settings()
    assert s.provider == "openai" and s.resolved_model == "gpt-6-luna"
    assert s.retriever == "hybrid" and s.qa_prompt_version == "v3"


def test_settings_from_env_parses_and_validates():
    s = Settings.from_env(
        {
            "DOCINTEL_PROVIDER": "Anthropic",
            "DOCINTEL_TOP_K": "5",
            "DOCINTEL_MODEL": "",
            "DOCINTEL_TEMPERATURE": "0.2",
        }
    )
    assert s.provider == "anthropic" and s.top_k == 5 and s.model is None and s.temperature == 0.2
    assert s.resolved_model == DEFAULT_MODEL_BY_PROVIDER["anthropic"]


def test_empty_reasoning_effort_means_not_sent():
    assert Settings.from_env({"DOCINTEL_REASONING_EFFORT": ""}).reasoning_effort is None


@pytest.mark.parametrize(
    "env",
    [
        {"DOCINTEL_PROVIDER": "skynet"},
        {"DOCINTEL_TOP_K": "zero"},
        {"DOCINTEL_CHUNK_OVERLAP": "900"},
        {"DOCINTEL_QA_PROMPT_VERSION": "v7"},
        {"DOCINTEL_MAX_RETRIES": "50"},
    ],
)
def test_invalid_environment_values_raise_clear_errors(env):
    with pytest.raises(ConfigError) as err:
        Settings.from_env(env)
    assert "DOCINTEL_" in str(err.value)


def test_unknown_settings_are_rejected():
    with pytest.raises(ValueError):
        Settings(not_a_setting=1)


def test_every_default_model_is_priced_in_the_catalog():
    for provider, model in DEFAULT_MODEL_BY_PROVIDER.items():
        if provider != "mock":
            info = get_model_info(model)
            assert info is not None and info.provider == provider


def test_catalog_entries_have_sources_and_positive_prices():
    for info in CATALOG:
        assert info.source_url.startswith("https://")
        assert info.input_per_mtok > 0 and info.output_per_mtok > 0 and info.context_window > 0
