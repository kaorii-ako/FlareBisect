import json

import pytest

from flarebisect import config as config_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for var in config_store.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def write_raw(text):
    path = config_store.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestCorruptConfigRecovery:
    """A broken config must not take down the CLI — including the very command
    you would use to repair it."""

    def test_truncated_json_falls_back_to_defaults(self, capsys):
        write_raw('{"provider": "anthropic", truncated...')
        assert config_store.load() == config_store.defaults()
        assert "ignoring unreadable config" in capsys.readouterr().err

    def test_json_that_is_not_an_object_falls_back(self, capsys):
        write_raw("[1, 2, 3]")
        assert config_store.load() == config_store.defaults()
        assert "malformed" in capsys.readouterr().err

    def test_providers_key_of_wrong_type_is_replaced(self):
        write_raw('{"provider": "openai", "providers": "nope"}')
        assert config_store.load()["providers"] == {}

    def test_set_key_repairs_a_corrupt_file(self):
        write_raw("}{ not json")
        config_store.set_key("openai", "sk-test")
        assert json.loads(config_store.config_path().read_text())["providers"]["openai"]["api_key"] == "sk-test"

    def test_resolve_works_with_a_corrupt_file(self):
        write_raw("garbage")
        assert config_store.resolve().name == config_store.DEFAULT_PROVIDER


class TestRoundTrip:
    def test_key_model_and_base_url_persist(self):
        config_store.set_key("custom", "sk-x")
        config_store.set_model("custom", "my-model")
        config_store.set_base_url("custom", "http://localhost:9/v1")
        cfg = config_store.resolve(provider="custom")
        assert (cfg.api_key, cfg.model, cfg.base_url) == ("sk-x", "my-model", "http://localhost:9/v1")

    def test_explicit_overrides_beat_stored_values(self):
        config_store.set_key("openai", "stored")
        assert config_store.resolve(provider="openai", api_key="passed").api_key == "passed"

    def test_env_var_is_the_fallback_when_nothing_stored(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "from-env")
        assert config_store.resolve(provider="openai").api_key == "from-env"

    def test_stored_key_beats_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "from-env")
        config_store.set_key("openai", "from-file")
        assert config_store.resolve(provider="openai").api_key == "from-file"

    def test_use_provider_changes_the_default(self):
        config_store.use_provider("ollama")
        assert config_store.resolve().name == "ollama"
