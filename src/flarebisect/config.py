"""Persisted CLI settings: default provider + per-provider api key/model/base_url.

Stored as JSON under the OS config dir so `flarebisect config set-key ...` sticks
across shells and reboots without env vars. Falls back to per-provider env vars
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY) when nothing is stored."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .providers import ProviderConfig

ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}

DEFAULT_PROVIDER = "anthropic"


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home()))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "flarebisect"


def config_path() -> Path:
    return config_dir() / "config.json"


def defaults() -> dict:
    return {"provider": DEFAULT_PROVIDER, "providers": {}}


def load() -> dict:
    """Read stored settings, falling back to defaults if the file is unusable.

    A hand-edited or truncated config must not take the whole CLI down with a
    JSONDecodeError — that would also break `config set-key`, the very command
    you'd reach for to repair it. Warn and carry on with defaults instead; the
    next `save()` rewrites the file cleanly.
    """
    path = config_path()
    if not path.exists():
        return defaults()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"warning: ignoring unreadable config at {path} ({e})", file=sys.stderr)
        return defaults()
    if not isinstance(data, dict):
        print(f"warning: ignoring malformed config at {path} (expected an object)", file=sys.stderr)
        return defaults()
    data.setdefault("providers", {})
    if not isinstance(data["providers"], dict):
        data["providers"] = {}
    return data


def save(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    if os.name != "nt":
        path.chmod(0o600)


def set_key(provider: str, api_key: str) -> None:
    data = load()
    data.setdefault("providers", {}).setdefault(provider, {})["api_key"] = api_key
    save(data)


def set_model(provider: str, model: str) -> None:
    data = load()
    data.setdefault("providers", {}).setdefault(provider, {})["model"] = model
    save(data)


def set_base_url(provider: str, base_url: str) -> None:
    data = load()
    data.setdefault("providers", {}).setdefault(provider, {})["base_url"] = base_url
    save(data)


def use_provider(provider: str) -> None:
    data = load()
    data["provider"] = provider
    save(data)


def resolve(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ProviderConfig:
    data = load()
    name = provider or data.get("provider", DEFAULT_PROVIDER)
    stored = data.get("providers", {}).get(name, {})

    resolved_key = api_key or stored.get("api_key") or os.environ.get(ENV_KEYS.get(name, ""), None)
    resolved_model = model or stored.get("model")
    resolved_base_url = base_url or stored.get("base_url")

    return ProviderConfig(name=name, api_key=resolved_key, model=resolved_model, base_url=resolved_base_url)
