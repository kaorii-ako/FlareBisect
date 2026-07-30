"""Ask the configured LLM for a short root-cause read.

Two shapes: `explain` for a bisected culprit commit (diff + failure output),
and `explain_failures` for diagnose mode, where there is no commit to blame
and the only evidence is how the command failed."""

from __future__ import annotations

from .bisect import BisectOutcome
from .diagnose import DiagnoseOutcome
from .failures import FailureMode
from .providers import ProviderConfig, complete

MAX_DIFF_CHARS = 6000
MAX_OUTPUT_CHARS = 2500

PROMPT_TEMPLATE = """A commit changed a command's failure rate. Diagnose the likely cause.

command: {command}
commit {sha}: "{subject}"

failure rate before: {before_rate:.0%}
failure rate after:  {culprit_rate:.0%}
bisection threshold: {threshold:.0%}
verdict: {verdict}
{failures}
diff:
```diff
{diff}
```

Answer in exactly 1-2 short sentences, no preamble, no restating the numbers above.
Point at the specific code change responsible (shared state, missing lock, timing/ordering
assumption, resource leak, off-by-one, whatever it actually is)."""

DIAGNOSE_TEMPLATE = """A command fails intermittently. Diagnose the likely cause.

command: {command}
failure rate: {rate:.0%} ({failed} of {runs} runs failed)
distinct failure modes: {mode_count}
{modes}
Answer in exactly 2-3 short sentences, no preamble, no restating the numbers above.
Name the most likely underlying cause (race condition, shared state between parallel
runs, test-order dependency, unwaited async work, network/clock/filesystem assumption,
resource exhaustion, whatever the output actually points at), and say what to check first."""


def _format_modes(modes: list[FailureMode], total_failures: int, limit: int = 3) -> str:
    if not modes:
        return ""
    blocks = []
    for i, mode in enumerate(modes[:limit], start=1):
        blocks.append(
            f"failure mode {i} — {mode.count}/{total_failures} of the failures:\n"
            f"```\n{mode.sample[-MAX_OUTPUT_CHARS:]}\n```"
        )
    if len(modes) > limit:
        blocks.append(f"({len(modes) - limit} further, rarer failure modes omitted)")
    return "\n" + "\n\n".join(blocks) + "\n"


def explain(
    outcome: BisectOutcome,
    diff: str,
    threshold: float,
    provider_cfg: ProviderConfig,
) -> str:
    modes = outcome.failure_modes
    prompt = PROMPT_TEMPLATE.format(
        command=outcome.command or "(unspecified)",
        sha=outcome.culprit.sha[:12],
        subject=outcome.culprit.subject,
        before_rate=outcome.before.result.flake_rate,
        culprit_rate=outcome.culprit.result.flake_rate,
        threshold=threshold,
        verdict=outcome.verdict,
        failures=_format_modes(modes, outcome.culprit.result.failed),
        diff=diff[:MAX_DIFF_CHARS],
    )
    return complete(provider_cfg, prompt)


def explain_failures(outcome: DiagnoseOutcome, provider_cfg: ProviderConfig) -> str:
    prompt = DIAGNOSE_TEMPLATE.format(
        command=outcome.command,
        rate=outcome.result.flake_rate,
        failed=outcome.result.failed,
        runs=outcome.result.runs,
        mode_count=len(outcome.modes),
        modes=_format_modes(outcome.modes, outcome.result.failed),
    )
    return complete(provider_cfg, prompt, max_tokens=400)
