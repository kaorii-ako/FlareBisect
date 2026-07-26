"""Ask the configured LLM for a short root-cause read on the culprit commit."""

from __future__ import annotations

from .bisect import BisectOutcome
from .providers import ProviderConfig, complete

PROMPT_TEMPLATE = """A commit changed a test's failure rate. Diagnose the likely cause.

commit {sha}: "{subject}"

flake rate before: {before_rate:.0%}
flake rate after:  {culprit_rate:.0%}
bisection threshold: {threshold:.0%}
verdict: {verdict}

diff:
```diff
{diff}
```

Answer in exactly 1-2 short sentences, no preamble, no restating the numbers above.
Point at the specific code change responsible (shared state, missing lock, timing/ordering
assumption, resource leak, off-by-one, whatever it actually is)."""


def explain(outcome: BisectOutcome, diff: str, threshold: float, provider_cfg: ProviderConfig) -> str:
    prompt = PROMPT_TEMPLATE.format(
        sha=outcome.culprit.sha[:12],
        subject=outcome.culprit.subject,
        before_rate=outcome.before.result.flake_rate,
        culprit_rate=outcome.culprit.result.flake_rate,
        threshold=threshold,
        verdict=outcome.verdict,
        diff=diff[:6000],
    )
    return complete(provider_cfg, prompt)
