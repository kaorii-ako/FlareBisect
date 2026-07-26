from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from . import __version__, ai_explain, git_ops, report
from .bisect import run_bisect

app = typer.Typer(add_completion=False, help="git bisect that treats flakiness as a signal, not noise.")


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
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Call Claude for a root-cause explanation."),
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

    def on_measure(label: str, m):
        report.print_measurement(label, m)

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

    report.print_result(outcome, threshold)

    if explain:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            report.print_error("ANTHROPIC_API_KEY not set — skipping AI explanation.")
            raise typer.Exit(0)
        diff = git_ops.commit_diff(repo, outcome.culprit.sha)
        try:
            text = ai_explain.explain(outcome, diff, threshold)
            report.print_explanation(text)
        except Exception as e:  # noqa: BLE001 - surface any SDK/network error to the user
            report.print_error(f"AI explanation failed: {e}")


if __name__ == "__main__":
    app()
