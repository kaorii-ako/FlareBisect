"""LLM backend abstraction.

Claude talks over Anthropic's native SDK. Everything else - OpenAI, Gemini,
Ollama, LM Studio, llama.cpp server, vLLM, Groq, OpenRouter, whatever -
speaks the same OpenAI-style chat completions shape, so one client covers
all of them by swapping base_url."""

from __future__ import annotations

from dataclasses import dataclass

PROVIDERS = ("anthropic", "openai", "google", "ollama", "custom")

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "ollama": "http://localhost:11434/v1",
}

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1-mini",
    "google": "gemini-2.5-flash",
    "ollama": "llama3.1",
}

# local/self-hosted servers usually don't check the key at all
NO_KEY_REQUIRED = {"ollama", "custom"}


@dataclass
class ProviderConfig:
    name: str
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None

    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.name, "gpt-4o-mini")

    def resolved_base_url(self) -> str | None:
        return self.base_url or DEFAULT_BASE_URLS.get(self.name)


class ProviderError(RuntimeError):
    pass


def complete(cfg: ProviderConfig, prompt: str, max_tokens: int = 300) -> str:
    if cfg.name not in PROVIDERS:
        raise ProviderError(f"unknown provider '{cfg.name}' (expected one of {', '.join(PROVIDERS)})")

    if cfg.name == "anthropic":
        return _complete_anthropic(cfg, prompt, max_tokens)
    return _complete_openai_compatible(cfg, prompt, max_tokens)


def _complete_anthropic(cfg: ProviderConfig, prompt: str, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise ProviderError("anthropic package not installed (pip install anthropic)") from e

    if not cfg.api_key:
        raise ProviderError(
            "no Anthropic API key configured. Run `flarebisect config set-key anthropic <key>` "
            "or set ANTHROPIC_API_KEY"
        )

    client = anthropic.Anthropic(api_key=cfg.api_key)
    try:
        message = client.messages.create(
            model=cfg.resolved_model(),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise ProviderError(str(e)) from e

    return "".join(block.text for block in message.content if hasattr(block, "text")).strip()


def _complete_openai_compatible(cfg: ProviderConfig, prompt: str, max_tokens: int) -> str:
    try:
        import openai
    except ImportError as e:
        raise ProviderError("openai package not installed (pip install openai)") from e

    api_key = cfg.api_key
    if not api_key:
        if cfg.name in NO_KEY_REQUIRED:
            api_key = "not-needed"
        else:
            raise ProviderError(
                f"no API key configured for '{cfg.name}'. Run "
                f"`flarebisect config set-key {cfg.name} <key>` or set the matching env var"
            )

    client = openai.OpenAI(api_key=api_key, base_url=cfg.resolved_base_url())
    try:
        response = client.chat.completions.create(
            model=cfg.resolved_model(),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except openai.APIError as e:
        raise ProviderError(str(e)) from e

    return (response.choices[0].message.content or "").strip()
