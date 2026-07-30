from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from . import __version__, ai_explain, config as config_store, git_ops, hardware, report, toolchains
from .bisect import run_bisect
from .diagnose import run_diagnose
from .providers import DEFAULT_BASE_URLS, DEFAULT_MODELS, NO_KEY_REQUIRED, PROVIDERS, ProviderError

app = typer.Typer(
    add_completion=False,
    help="Find what made a command flaky — in any language, with or without a commit range.",
)
config_app = typer.Typer(add_completion=False, help="Manage stored AI provider settings.")
models_app = typer.Typer(add_completion=False, help="Detect your GPU/VRAM and manage local Ollama models.")
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")

PROVIDER_BLURBS = {
    "anthropic": "Claude, cloud, needs an API key",
    "openai": "GPT models, cloud, needs an API key",
    "google": "Gemini, cloud, needs an API key",
    "ollama": "local model via Ollama, no key needed",
    "custom": "any OpenAI-compatible endpoint (LM Studio, llama.cpp, vLLM...)",
}


@app.command()
def version() -> None:
    """Show the flarebisect version."""
    typer.echo(__version__)


@app.command()
def run(
    good: str = typer.Option(..., "--good", help="Known-good commit/ref."),
    bad: str = typer.Option(..., "--bad", help="Known-bad (or known-flaky) commit/ref."),
    cmd: Optional[str] = typer.Option(
        None,
        "--cmd",
        "--test",
        help="Command to run, e.g. 'npm test' or 'pytest -k my_test'. Defaults to the detected toolchain's.",
    ),
    setup: Optional[str] = typer.Option(
        None, "--setup", help="One-time prep per worktree, e.g. 'npm ci'. Defaults to the detected toolchain's."
    ),
    no_setup: bool = typer.Option(False, "--no-setup", help="Skip the setup step entirely."),
    repo: Path = typer.Option(Path.cwd(), "--repo", help="Path to the git repository."),
    runs: int = typer.Option(20, "--runs", min=1, help="Command runs per commit."),
    threshold: float = typer.Option(
        0.3, "--threshold", min=0.0, max=1.0, help="Failure-rate jump that counts as the culprit (0-1)."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", min=0.001, help="Seconds before a single run is treated as hung and killed."
    ),
    setup_timeout: Optional[float] = typer.Option(
        600.0, "--setup-timeout", min=0.001, help="Seconds before the setup step is given up on."
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        min=1,
        help="Runs to execute at once (default: core count). Use --workers 1 for a suite that "
        "isn't safe to run concurrently — fixed ports, a shared scratch file, one test database.",
    ),
    share_cache: bool = typer.Option(
        True,
        "--share-cache/--no-share-cache",
        help="Point package-manager caches at one shared dir so deps download once, not once per commit.",
    ),
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
    """Bisect on failure-rate jump instead of pass/fail."""
    report.print_banner()
    repo = repo.resolve()

    try:
        git_ops.resolve_sha(repo, good)
        git_ops.resolve_sha(repo, bad)
    except git_ops.GitError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    try:
        plan = toolchains.resolve_plan(repo, cmd, setup, no_setup=no_setup)
    except ValueError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_plan(plan)
    env = toolchains.build_env(plan.toolchain, share_cache=share_cache)

    def on_measure(label: str, m) -> None:
        pass  # table is rendered once, after the search completes

    try:
        outcome = run_bisect(
            repo=repo,
            good=good,
            bad=bad,
            test_cmd=plan.command,
            runs=runs,
            threshold=threshold,
            on_measure=on_measure,
            setup_cmd=plan.setup,
            env=env,
            timeout=timeout,
            setup_timeout=setup_timeout,
            workers=workers,
            plan=plan,
        )
    except ValueError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_progress_line(outcome.total_commits, outcome.runs, outcome.workers)
    report.print_table(outcome.measurements)

    report.print_failure_modes(outcome.failure_modes, outcome.focus.result.failed)

    explanation: Optional[str] = None
    # With no culprit, there is no diff worth explaining — asking anyway would
    # produce a confident root cause for a commit we have not implicated.
    if explain and outcome.culprit_found:
        provider_cfg = config_store.resolve(provider=provider, api_key=api_key, model=model, base_url=base_url)
        diff = git_ops.commit_diff(repo, outcome.culprit.sha)
        try:
            explanation = ai_explain.explain(outcome, diff, threshold, provider_cfg)
        except ProviderError as e:
            report.print_error(str(e))

    report.print_result(outcome, threshold, explanation)
    report.print_footer(outcome.elapsed_seconds, len(outcome.measurements), outcome.workers)


@app.command()
def diagnose(
    cmd: Optional[str] = typer.Option(
        None, "--cmd", "--test", help="Command to run repeatedly. Defaults to the detected toolchain's."
    ),
    path: Path = typer.Option(Path.cwd(), "--path", "--repo", help="Directory to run in (a git repo is optional)."),
    ref: Optional[str] = typer.Option(
        None, "--ref", help="Run against an isolated worktree at this commit instead of the working tree."
    ),
    runs: int = typer.Option(20, "--runs", min=1, help="How many times to run the command."),
    setup: Optional[str] = typer.Option(None, "--setup", help="One-time prep before the runs."),
    setup_first: Optional[bool] = typer.Option(
        None,
        "--setup-first/--no-setup-first",
        help="Run the setup step before measuring. Default: only with --ref, since a fresh "
        "worktree needs building but your working tree already is.",
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", min=0.001, help="Seconds before a single run is treated as hung and killed."
    ),
    setup_timeout: Optional[float] = typer.Option(
        600.0, "--setup-timeout", min=0.001, help="Seconds to allow for setup."
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        min=1,
        help="Runs to execute at once (default: core count). Use --workers 1 for a suite that "
        "isn't safe to run concurrently.",
    ),
    share_cache: bool = typer.Option(True, "--share-cache/--no-share-cache", help="Share package-manager caches."),
    show_output: bool = typer.Option(
        True, "--show-output/--no-show-output", help="Print a tail of the most common failure."
    ),
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Call an LLM for a root-cause explanation."),
    provider: Optional[str] = typer.Option(None, "--provider", help=f"One of {', '.join(PROVIDERS)}."),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="Override the stored/env API key for this run."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the model for this run."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Override the API base URL."),
) -> None:
    """Diagnose a flaky command with no commit range — run it N times and cluster how it fails."""
    report.print_banner()
    path = path.resolve()

    if not path.is_dir():
        report.print_error(f"not a directory: {path}")
        raise typer.Exit(1)

    # A --ref run happens in a fresh worktree that has to be built; an in-place
    # run reuses whatever the caller has already built. An explicit flag wins.
    setup_wanted = setup_first if setup_first is not None else (ref is not None)
    try:
        plan = toolchains.resolve_plan(path, cmd, setup, no_setup=not setup_wanted)
    except ValueError as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_plan(
        plan,
        skip_reason="--no-setup-first" if setup_first is False else "working tree already built",
    )
    env = toolchains.build_env(plan.toolchain, share_cache=share_cache)

    try:
        outcome = run_diagnose(
            workdir=path,
            command=plan.command,
            runs=runs,
            repo=path if ref else None,
            ref=ref,
            setup_cmd=plan.setup,
            env=env,
            timeout=timeout,
            setup_timeout=setup_timeout,
            workers=workers,
            plan=plan,
        )
    except (ValueError, git_ops.GitError) as e:
        report.print_error(str(e))
        raise typer.Exit(1)

    report.print_diagnose_summary(outcome)
    report.print_failure_modes(outcome.modes, outcome.result.failed)
    if show_output and outcome.modes:
        report.print_excerpt(outcome.modes[0])

    explanation: Optional[str] = None
    if explain and outcome.result.failed and not outcome.result.setup_failed:
        provider_cfg = config_store.resolve(provider=provider, api_key=api_key, model=model, base_url=base_url)
        try:
            explanation = ai_explain.explain_failures(outcome, provider_cfg)
        except ProviderError as e:
            report.print_error(str(e))

    report.print_diagnose_result(outcome, explanation)
    report.print_footer(outcome.elapsed_seconds, outcome.runs, outcome.workers, label="runs")


@app.command()
def detect(
    path: Path = typer.Option(Path.cwd(), "--path", "--repo", help="Directory to inspect."),
) -> None:
    """Show the toolchain FlareBisect detects here, and the commands it would run."""
    console = report.console
    path = path.resolve()
    found = toolchains.detect_all(path)

    console.print()
    if not found:
        console.print(f"[yellow]no toolchain detected[/yellow] in {escape(str(path))}")
        console.print("[dim]pass --cmd \"<command>\" (and --setup if it needs building) explicitly[/dim]")
        return

    primary = found[0]
    console.print(f"[dim]inspecting[/dim] {escape(str(path))}")
    console.print()
    for tc in found:
        marker = "[bold cyan]→[/bold cyan]" if tc is primary else " "
        console.print(f"{marker} [bold]{tc.name}[/bold]")
        console.print(f"    [dim]command:[/dim] {tc.test}")
        console.print(f"    [dim]setup:[/dim]   {tc.setup or '(none needed)'}")
        if tc.cache_env:
            console.print(f"    [dim]shared cache:[/dim] {', '.join(sorted(tc.cache_env))}")

    if len(found) > 1:
        console.print()
        console.print(
            f"[dim]{len(found)} toolchains present — [bold]{primary.name}[/bold] wins by default; "
            "override with --cmd/--setup[/dim]"
        )
    console.print()


@config_app.callback(invoke_without_command=True)
def config_main(ctx: typer.Context) -> None:
    """Manage stored AI provider settings. Run with no subcommand for a guided setup."""
    if ctx.invoked_subcommand is None:
        config_wizard()


def config_wizard() -> None:
    console = report.console
    console.print()
    console.print(Panel.fit("[bold]flarebisect setup[/bold] — pick an AI provider for root-cause explanations", border_style="grey50"))

    console.print()
    console.print("[bold]step 1/4[/bold] — provider")
    for i, name in enumerate(PROVIDERS, start=1):
        console.print(f"  [cyan]{i}[/cyan]) {name:<10} [dim]{PROVIDER_BLURBS[name]}[/dim]")
    choice = Prompt.ask("  choose", choices=[str(i) for i in range(1, len(PROVIDERS) + 1)], default="1")
    provider = PROVIDERS[int(choice) - 1]

    base_url = None
    api_key = None

    if provider in ("ollama", "custom"):
        console.print()
        console.print("[bold]step 2/4[/bold] — endpoint")
        default_url = DEFAULT_BASE_URLS.get(provider, "http://localhost:11434/v1")
        base_url = Prompt.ask("  base URL", default=default_url)

        if provider in NO_KEY_REQUIRED:
            needs_key = Confirm.ask("  does this endpoint require an API key?", default=False)
        else:
            needs_key = True
        if needs_key:
            api_key = Prompt.ask("  API key", password=True)
    else:
        console.print()
        console.print("[bold]step 2/4[/bold] — API key")
        console.print(f"  [dim]leave blank to fall back to the {config_store.ENV_KEYS.get(provider)} env var[/dim]")
        entered = Prompt.ask("  API key", password=True, default="", show_default=False)
        api_key = entered or None

    console.print()
    console.print("[bold]step 3/4[/bold] — model")
    default_model = DEFAULT_MODELS.get(provider, "")
    if provider == "ollama":
        gpu = hardware.detect_gpu()
        recommended, desc = hardware.recommend_model_with_desc(gpu.vram_gb)
        if gpu.vendor == "none":
            console.print("  [dim]no dedicated GPU detected — recommending a small CPU-friendly model[/dim]")
        else:
            console.print(f"  [dim]detected {escape(gpu.name)} (~{gpu.vram_gb} GB VRAM)[/dim]")
        console.print(f"  [dim]recommended: {escape(recommended)} — {desc}[/dim]")
        default_model = recommended
    model = Prompt.ask("  model", default=default_model)

    console.print()
    console.print("[bold]step 4/4[/bold] — confirm")
    make_active = Confirm.ask(f"  set '{provider}' as the active provider?", default=True)

    if api_key:
        config_store.set_key(provider, api_key)
    if model:
        config_store.set_model(provider, model)
    if base_url:
        config_store.set_base_url(provider, base_url)
    if make_active:
        config_store.use_provider(provider)

    if provider == "ollama":
        if hardware.ollama_available():
            if Confirm.ask(f"  pull '{model}' now via ollama?", default=True):
                console.print()
                try:
                    hardware.pull_model(model)
                    console.print(f"[green]pulled {escape(model)}[/green]")
                except (RuntimeError, subprocess.CalledProcessError) as e:
                    report.print_error(f"pull failed: {e}")
        else:
            console.print(
                "  [yellow]ollama not found on PATH[/yellow] — install it from https://ollama.com, "
                "then run `flarebisect models pull`"
            )

    masked_key = f"...{api_key[-4:]}" if api_key and len(api_key) > 4 else ("(none)" if not api_key else "(set)")
    console.print()
    console.print(
        Panel.fit(
            f"[bold green]saved[/bold green] — provider={provider}  model={escape(model)}\n"
            f"key={masked_key}"
            + (f"  base_url={escape(base_url)}" if base_url else "")
            + f"\n\n[dim]config file: {config_store.config_path()}[/dim]\n"
            f"[dim]next: flarebisect run --good <sha> --bad <sha> --test \"...\"[/dim]",
            border_style="green",
        )
    )


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


@models_app.command("detect")
def models_detect() -> None:
    """Detect your GPU/VRAM and show the recommended local model."""
    console = report.console
    gpu = hardware.detect_gpu()
    model, desc = hardware.recommend_model_with_desc(gpu.vram_gb)
    console.print()
    if gpu.vendor == "none":
        console.print("[yellow]no dedicated GPU detected[/yellow] — falling back to a small CPU-friendly model")
    else:
        console.print(f"GPU: [bold]{escape(gpu.name)}[/bold] ({gpu.vendor}) — ~{gpu.vram_gb} GB VRAM")
    console.print(f"recommended model: [bold cyan]{escape(model)}[/bold cyan] — {desc}")
    console.print("[dim]run `flarebisect models pull` to download it[/dim]")


@models_app.command("pull")
def models_pull(
    model: Optional[str] = typer.Argument(None, help="Model tag to pull (default: auto-detected from your GPU)."),
    set_active: bool = typer.Option(
        True, "--set-active/--no-set-active", help="Set ollama as the active provider with this model."
    ),
) -> None:
    """Download a local model via Ollama, sized to your GPU's VRAM."""
    console = report.console
    gpu = hardware.detect_gpu()
    chosen = model or hardware.recommend_model(gpu.vram_gb)
    if not model:
        console.print(f"detected [bold]{escape(gpu.name)}[/bold] (~{gpu.vram_gb} GB VRAM) — pulling [bold cyan]{escape(chosen)}[/bold cyan]")
    else:
        console.print(f"pulling [bold cyan]{escape(chosen)}[/bold cyan]")

    try:
        hardware.pull_model(chosen)
    except RuntimeError as e:
        report.print_error(str(e))
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        report.print_error(f"ollama pull failed: {e}")
        raise typer.Exit(1)

    if set_active:
        config_store.set_model("ollama", chosen)
        config_store.use_provider("ollama")
        console.print(f"[green]saved[/green] — active provider set to ollama / {escape(chosen)}")


if __name__ == "__main__":
    app()
