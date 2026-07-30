from __future__ import annotations

from rich import box
from rich.bar import Bar
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .bisect import BisectOutcome, CommitMeasurement
from .diagnose import DiagnoseOutcome
from .failures import FailureMode
from .toolchains import Plan

console = Console()

BAR_WIDTH = 42
TRACK_COLOR = "grey19"

STATUS_STYLE = {
    "good": "green3",
    "stable": "green3",
    "wobbling": "gold3",
    "flare": "bold dark_orange",
    "bad": "red3",
    "setup": "magenta3",
}

BAR_COLOR = {
    "good": "grey19",
    "stable": "grey19",
    "wobbling": "gold3",
    "flare": "dark_orange",
    "bad": "red3",
    "setup": "magenta3",
}

MODE_COLORS = ("dark_orange", "gold3", "cyan3", "magenta3", "grey50")


def print_banner() -> None:
    dot_styles = ["grey35", "grey42", "grey50", "gold3", "dark_orange", "bold dark_orange"]
    spark_col = 3 * (len(dot_styles) - 1)

    console.print()
    console.print(Text(" " * spark_col + "✦", style="bold dark_orange"))

    line = Text()
    for i, style in enumerate(dot_styles):
        if i:
            line.append("──", style="grey19")
        line.append("●", style=style)
    line.append("   ")
    line.append("FlareBisect", style="bold white")
    console.print(line)


def print_plan(plan: Plan | None, skip_reason: str = "--no-setup") -> None:
    """Show what will be run and whether we inferred it or were told."""
    if plan is None:
        return

    console.print()
    tc = plan.toolchain.name if plan.toolchain else "unknown"
    detected = "detected" if plan.command_source == "toolchain" else "toolchain"
    console.print(f"[dim]{detected}:[/dim] [cyan]{tc}[/cyan]")

    # Commands legitimately contain brackets (`pytest -k "test[1]"`), which Rich
    # would otherwise eat as markup and print a command we did not run.
    cmd_note = "" if plan.command_source == "flag" else "  [dim](default for this toolchain)[/dim]"
    console.print(f"[dim]command:[/dim]  {escape(plan.command)}{cmd_note}")

    if plan.setup:
        setup_note = "" if plan.setup_source == "flag" else "  [dim](inferred — override with --setup)[/dim]"
        console.print(f"[dim]setup:[/dim]    {escape(plan.setup)}{setup_note}")
    elif plan.setup_source == "disabled":
        console.print(f"[dim]setup:[/dim]    [dim]skipped ({skip_reason})[/dim]")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def print_progress_line(total_commits: int, runs: int, workers: int) -> None:
    console.print()
    console.print(
        f"[dim]{_plural(total_commits, 'commit')} in range · {runs} runs per commit · "
        f"parallel worktrees ({_plural(workers, 'worker')})[/dim]"
    )
    console.print()


def _row(m: CommitMeasurement) -> tuple:
    short_sha = m.sha[:7]
    is_flare = m.status == "flare"
    commit_text = Text(short_sha, style="bold white" if is_flare else "grey70")

    bar = Bar(
        size=1.0,
        begin=0,
        end=m.result.flake_rate,
        width=BAR_WIDTH,
        color=BAR_COLOR.get(m.status, "grey50"),
        bgcolor=TRACK_COLOR,
    )

    result_text = Text(f"{m.result.passed}/{m.result.runs}", style="bold white" if is_flare else "grey70")
    status_text = Text(m.status, style=STATUS_STYLE.get(m.status, "grey70"))

    return commit_text, bar, result_text, status_text


def print_table(measurements: list[CommitMeasurement]) -> None:
    table = Table(box=None, show_header=True, header_style="dim", padding=(0, 2, 0, 0))
    table.add_column("commit")
    table.add_column("flake rate")
    table.add_column("result", justify="right")
    table.add_column("status")

    for m in measurements:
        table.add_row(*_row(m))

    console.print(table)


def print_failure_modes(modes: list[FailureMode], total_failures: int, limit: int = 5) -> None:
    """How the command failed, grouped — one cluster or several unrelated ones."""
    if not modes:
        return

    console.print()
    noun = "way" if len(modes) == 1 else "ways"
    console.print(f"[dim]{len(modes)} distinct {noun} it failed[/dim]")
    console.print()

    table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    table.add_column("share", justify="right")
    table.add_column("bar")
    table.add_column("headline", overflow="ellipsis", max_width=64)

    for i, mode in enumerate(modes[:limit]):
        color = MODE_COLORS[min(i, len(MODE_COLORS) - 1)]
        bar = Bar(
            size=1.0,
            begin=0,
            end=mode.share(total_failures),
            width=18,
            color=color,
            bgcolor=TRACK_COLOR,
        )
        table.add_row(
            Text(f"{mode.count}×", style="grey70"),
            bar,
            Text(mode.headline, style="grey70" if i else "white"),
        )

    console.print(table)
    if len(modes) > limit:
        console.print(f"[dim]  … {len(modes) - limit} rarer {'mode' if len(modes) - limit == 1 else 'modes'}[/dim]")


def print_inconclusive(outcome: BisectOutcome, threshold: float) -> None:
    """No commit crossed the threshold — say that, don't invent a culprit."""
    peak = max(outcome.measurements, key=lambda m: m.result.flake_rate)
    baseline = outcome.good_baseline.flake_rate

    lines = [
        Text.from_markup("[bold]· inconclusive[/bold] · no commit crossed the threshold"),
        Text(""),
        Text.from_markup(
            f"highest rate seen was [bold]{peak.result.flake_rate:.0%}[/bold] at "
            f"[bold]{peak.sha[:7]}[/bold], a "
            f"[bold]{peak.result.flake_rate - baseline:+.0%}[/bold] move off the "
            f"{baseline:.0%} baseline — under the {threshold:.0%} threshold."
        ),
        Text(""),
        Text.from_markup(
            "[grey70]Either the regression is subtler than the threshold, or the sample is "
            "too small to separate it from noise. Try [bold]--threshold "
            f"{max(0.05, (peak.result.flake_rate - baseline) * 0.8):.2f}[/bold] or a higher "
            "[bold]--runs[/bold].[/grey70]"
        ),
    ]

    console.print()
    console.print(Panel(Group(*lines), border_style="gold3", padding=(1, 2)))


def print_result(outcome: BisectOutcome, threshold: float, explanation: str | None = None) -> None:
    if not outcome.culprit_found:
        print_inconclusive(outcome, threshold)
        return

    before_pct = outcome.before.result.flake_rate
    after_pct = outcome.culprit.result.flake_rate

    header = Text.from_markup(
        f"[bold]✦ culprit found[/bold] · commit [bold]{outcome.culprit.sha[:7]}[/bold]"
        f"  [dim]{outcome.verdict}[/dim]"
    )
    body_lines = [
        header,
        Text(""),
        Text.from_markup(
            f"failure rate jumped [bold]{before_pct:.0%} → {after_pct:.0%}[/bold] at this commit"
        ),
        Text(f'"{outcome.culprit.subject}"', style="italic grey70"),
    ]

    if outcome.culprit.result.setup_failed:
        body_lines.append(Text(""))
        body_lines.append(
            Text.from_markup(
                "[magenta3]setup failed at this commit[/magenta3] — the tree stopped building "
                "here, so the command never ran"
            )
        )
    elif outcome.culprit.result.timeouts:
        n = outcome.culprit.result.timeouts
        body_lines.append(
            Text.from_markup(f"[dim]{n} of those runs hung and were killed by --timeout[/dim]")
        )

    renderables = [*body_lines]
    if explanation:
        renderables.append(Text(""))
        renderables.append(
            Panel(
                Text(f"💡 likely cause — {explanation}"),
                border_style="grey35",
                box=box.MINIMAL,
                style="on grey11",
                padding=(0, 2),
            )
        )

    console.print()
    console.print(Panel(Group(*renderables), border_style="red3", padding=(1, 2)))


def print_diagnose_summary(outcome: DiagnoseOutcome) -> None:
    console.print()
    where = f"at [bold]{escape(outcome.ref)}[/bold]" if outcome.ref else "in the working tree"
    console.print(
        f"[dim]{_plural(outcome.runs, 'run')} {where} · "
        f"parallel ({_plural(outcome.workers, 'worker')})[/dim]"
    )
    console.print()

    rate = outcome.result.flake_rate
    color = "green3" if rate == 0 else ("red3" if rate >= 1 else "gold3")
    bar = Bar(size=1.0, begin=0, end=rate, width=BAR_WIDTH, color=color, bgcolor=TRACK_COLOR)

    table = Table(box=None, show_header=True, header_style="dim", padding=(0, 2, 0, 0))
    table.add_column("failure rate")
    table.add_column("result", justify="right")
    table.add_column("verdict")
    table.add_row(
        bar,
        Text(f"{outcome.result.passed}/{outcome.result.runs}", style="bold white"),
        Text(outcome.verdict, style=color),
    )
    console.print(table)


def print_excerpt(mode: FailureMode) -> None:
    """A window of one representative failure, around the error — the receipts."""
    body = mode.excerpt()
    if not body:
        return
    console.print()
    console.print(
        Panel(
            Text(body, style="grey70"),
            title="[dim]most common failure[/dim]",
            title_align="left",
            border_style="grey35",
            box=box.MINIMAL,
            padding=(0, 2),
        )
    )


def print_diagnose_result(outcome: DiagnoseOutcome, explanation: str | None = None) -> None:
    if outcome.result.setup_failed:
        console.print()
        console.print(
            Panel(
                Text(outcome.result.setup_output[-1500:] or "(no output)", style="grey70"),
                title="[magenta3]setup failed[/magenta3]",
                title_align="left",
                border_style="magenta3",
                padding=(0, 2),
            )
        )
        return

    if outcome.result.failed == 0:
        console.print()
        console.print(
            Panel(
                Text.from_markup(
                    f"[bold green3]✓ no failures in {outcome.runs} runs[/bold green3]\n\n"
                    "[grey70]Either it isn't flaky here, or the conditions that trigger it "
                    "aren't present — try more --runs, or reproduce under load.[/grey70]"
                ),
                border_style="green3",
                padding=(1, 2),
            )
        )
        return

    renderables = [
        Text.from_markup(
            f"[bold]✦ {outcome.verdict}[/bold] · "
            f"[bold]{outcome.result.failed}/{outcome.runs}[/bold] runs failed"
        ),
        Text(""),
        Text(outcome.command, style="italic grey70"),
    ]
    if outcome.result.timeouts:
        renderables.append(
            Text.from_markup(f"[dim]{outcome.result.timeouts} run(s) hung and were killed[/dim]")
        )

    if explanation:
        renderables.append(Text(""))
        renderables.append(
            Panel(
                Text(f"💡 likely cause — {explanation}"),
                border_style="grey35",
                box=box.MINIMAL,
                style="on grey11",
                padding=(0, 2),
            )
        )

    console.print()
    console.print(Panel(Group(*renderables), border_style="dark_orange", padding=(1, 2)))


def print_footer(elapsed_seconds: float, checked: int, workers: int, label: str = "checked") -> None:
    console.print(
        f"[dim]⏱ {elapsed_seconds:.1f}s    ⚡ {checked} {label}    "
        f"⚙ {_plural(workers, 'parallel worker')}[/dim]"
    )
    console.print()


def print_error(message: str) -> None:
    # messages quote command output, which is full of brackets Rich would eat
    console.print(f"[bold red]error:[/bold red] {escape(message)}")
