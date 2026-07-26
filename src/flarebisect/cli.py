from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import __version__, ai_explain, config as config_store, git_ops, report
from .bisect import run_bisect
from .providers import PROVIDERS, ProviderError

app = typer.Typer(add_completion=False, help="git bisect that treats flakiness as a signal, not noise.")
config_app = typer.Typer(add_completion=False, help="Manage stored AI provider settings.")
app.add_typer(config_app, name="config")


@app.command()
def version() -> None:
    """Show the flarebisect version."""
    typer.echo(__version__)


@app.command()
def run(
    good: str = typer.Option(..., "--good", help="Known-good commit/ref."),
    bad: str = typer.Option(..., "--bad", help="Known-bad (or known-flaky) commit/ref."),
    test: str = typer.Option(..., "--test", help="Test command to run, e.g. 'pytest -k my_test'."),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Path to the git repository."),
    runs: int = typer.Option(5, "--runs", help="Test runs per commit."),
    threshold: float = typer.Option(0.3, "--threshold", help="Flake-rate jump that counts as the culprit (0-1)."),
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Call an LLM for a root-cause explanation."),
    provider: Optional[str] = typer.Option(
        None, "--provider", help=f"Override the default provider ({', '.join(PROVIDERS)})."
    ),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Override the stored/env API key for this run."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the model for this run."),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="Override the API base URL (for local/self-hosted servers)."
    ),
) -> None:
    """Bisect on flake-rate jump instead of pass/fail."""
    repo = repo.resolve()

    try:
        git_ops.resolve_sha(repo, good)
        git_ops.resolve_sha(repo, bad)
    except git_ops.GitError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_header(good, bad, test, runs, threshold)

    def on_measure(label: str, m) -> None:
        pass  # table is rendered once, after the search completes

    try:
        outcome = run_bisect(
            repo=repo,
            good=good,
            bad=bad,
            test_cmd=test,
            runs=runs,
            threshold=threshold,
            on_measure=on_measure,
        )
    except ValueError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_progress_line(outcome.total_commits, outcome.runs, outcome.workers)
    report.print_table(outcome.measurements)

    explanation: Optional[str] = None
    if explain:
        provider_cfg = config_store.resolve(provider=provider, api_key=api_key, model=model, base_url=base_url)
        diff = git_ops.commit_diff(repo, outcome.culprit.sha)
        try:
            explanation = ai_explain.explain(outcome, diff, threshold, provider_cfg)
        except ProviderError as e:
            report.print_error(str(e))

    report.print_result(outcome, threshold, explanation)
    report.print_footer(outcome.elapsed_seconds, len(outcome.measurements), outcome.workers)


@config_app.command("set-key")
def config_set_key(
    provider: str = typer.Argument(..., help=f"one of {', '.join(PROVIDERS)}"),
    api_key: str = typer.Argument(..., help="API key for this provider."),
) -> None:
    """Store an API key for a provider (local servers like Ollama usually don't need one)."""
    if provider not in PROVIDERS:
        report.print_error(f"unknown provider '{provider}' (expected one of {', '.join(PROVIDERS)})")
        raise typer.Exit(1)
    config_store.set_key(provider, api_key)
    typer.echo(f"stored API key for {provider} in {config_store.config_path()}")


@config_app.command("set-model")
def config_set_model(
    provider: str = typer.Argument(..., help=f"one of {', '.join(PROVIDERS)}"),
    model: str = typer.Argument(...),
) -> None:
    """Set the default model used for a provider."""
    if provider not in PROVIDERS:
        report.print_error(f"unknown provider '{provider}' (expected one of {', '.join(PROVIDERS)})")
        raise typer.Exit(1)
    config_store.set_model(provider, model)
    typer.echo(f"{provider} model set to {model}")


@config_app.command("set-base-url")
def config_set_base_url(
    provider: str = typer.Argument(..., help=f"one of {', '.join(PROVIDERS)}"),
    base_url: str = typer.Argument(..., help="e.g. http://localhost:11434/v1 for Ollama."),
) -> None:
    """Point a provider at a self-hosted / local endpoint."""
    if provider not in PROVIDERS:
        report.print_error(f"unknown provider '{provider}' (expected one of {', '.join(PROVIDERS)})")
        raise typer.Exit(1)
    config_store.set_base_url(provider, base_url)
    typer.echo(f"{provider} base URL set to {base_url}")


@config_app.command("use")
def config_use(provider: str = typer.Argument(..., help=f"one of {', '.join(PROVIDERS)}")) -> None:
    """Set the default provider used by `flarebisect run`."""
    if provider not in PROVIDERS:
        report.print_error(f"unknown provider '{provider}' (expected one of {', '.join(PROVIDERS)})")
        raise typer.Exit(1)
    config_store.use_provider(provider)
    typer.echo(f"default provider set to {provider}")


@config_app.command("show")
def config_show() -> None:
    """Show the current provider config (API keys masked)."""
    data = config_store.load()
    active = data.get("provider", config_store.DEFAULT_PROVIDER)
    typer.echo(f"active provider: {active}")
    typer.echo(f"config file: {config_store.config_path()}")
    typer.echo()
    for name in PROVIDERS:
        stored = data.get("providers", {}).get(name, {})
        key = stored.get("api_key")
        masked = f"...{key[-4:]}" if key and len(key) > 4 else ("(set)" if key else "(none)")
        marker = "*" if name == active else " "
        typer.echo(
            f"{marker} {name:<10} key={masked:<10} model={stored.get('model') or '(default)':<20} "
            f"base_url={stored.get('base_url') or '(default)'}"
        )


if __name__ == "__main__":
    app()
