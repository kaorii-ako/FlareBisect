from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .bisect import BisectOutcome, CommitMeasurement

console = Console()


def _rate_str(rate: float) -> str:
    color = "green" if rate <= 0.1 else "yellow" if rate < 0.9 else "red"
    return f"[{color}]{rate:.0%}[/{color}]"


def print_measurement(label: str, m: CommitMeasurement) -> None:
    console.print(
        f"  [dim]{label:<16}[/dim] {m.sha[:10]}  {_rate_str(m.result.flake_rate)}  "
        f"({m.result.failed}/{m.result.runs} failed)  [dim]{m.subject}[/dim]"
    )


def print_header(good: str, bad: str, test_cmd: str, runs: int, threshold: float) -> None:
    console.print()
    console.print(Panel.fit(
        f"[bold]flarebisect[/bold] — flake-aware bisection\n"
        f"good=[cyan]{good}[/cyan]  bad=[cyan]{bad}[/cyan]  runs=[cyan]{runs}[/cyan]  "
        f"threshold=[cyan]{threshold:.0%}[/cyan]\n"
        f"test: [italic]{test_cmd}[/italic]",
        border_style="bright_blue",
    ))
    console.print()


def print_result(outcome: BisectOutcome, threshold: float) -> None:
    table = Table(title="🔥 flare — culprit found", show_header=True, header_style="bold magenta")
    table.add_column("field")
    table.add_column("value")

    table.add_row("commit", outcome.culprit.sha[:12])
    table.add_row("message", outcome.culprit.subject)
    table.add_row("flake rate before", _rate_str(outcome.before.result.flake_rate))
    table.add_row("flake rate after", _rate_str(outcome.culprit.result.flake_rate))
    table.add_row("verdict", f"[bold]{outcome.verdict}[/bold]")

    console.print()
    console.print(table)


def print_explanation(text: str) -> None:
    console.print()
    console.print(Panel(Text(text), title="[bold]root cause (Claude)[/bold]", border_style="green"))


def print_error(message: str) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
