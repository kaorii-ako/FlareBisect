from __future__ import annotations

from rich import box
from rich.bar import Bar
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .bisect import BisectOutcome, CommitMeasurement

console = Console()

BAR_WIDTH = 42
TRACK_COLOR = "grey19"

STATUS_STYLE = {
    "good": "green3",
    "stable": "green3",
    "wobbling": "gold3",
    "flare": "bold dark_orange",
    "bad": "red3",
}

BAR_COLOR = {
    "good": "grey19",
    "stable": "grey19",
    "wobbling": "gold3",
    "flare": "dark_orange",
    "bad": "red3",
}


def print_header(good: str, bad: str, test_cmd: str, runs: int, threshold: float) -> None:
    console.print()
    console.print(f"[bold]$[/bold] flarebisect run --good {good} --bad {bad} --test \"{test_cmd}\"")


def print_progress_line(total_commits: int, runs: int, workers: int) -> None:
    console.print(
        f"[dim]{total_commits} commits in range · {runs} runs per commit · "
        f"parallel worktrees ({workers} workers)[/dim]"
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


def print_result(outcome: BisectOutcome, threshold: float, explanation: str | None = None) -> None:
    before_pct = outcome.before.result.flake_rate
    after_pct = outcome.culprit.result.flake_rate

    header = Text.from_markup(
        f"[bold]✦ culprit found[/bold] · commit [bold]{outcome.culprit.sha[:7]}[/bold]"
    )
    body_lines = [
        header,
        Text(""),
        Text.from_markup(
            f"flake rate jumped [bold]{before_pct:.0%} → {after_pct:.0%}[/bold] at this commit"
        ),
        Text(f'"{outcome.culprit.subject}"', style="italic grey70"),
    ]

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


def print_footer(elapsed_seconds: float, checked: int, workers: int) -> None:
    console.print(
        f"[dim]⏱ {elapsed_seconds:.1f}s    ⚡ {checked} checked    ⚙ {workers} parallel workers[/dim]"
    )
    console.print()


def print_error(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
