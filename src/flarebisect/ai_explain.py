"""Ask Claude for a plain-English root-cause explanation of the culprit commit."""

from __future__ import annotations

import os

from .bisect import BisectOutcome

DEFAULT_MODEL = os.environ.get("FLAREBISECT_MODEL", "claude-sonnet-5")

PROMPT_TEMPLATE = """You are helping a developer understand why a commit made a test flaky (or broke it outright).

Commit: {sha}
Message: {subject}

Flake-rate evidence:
- Baseline (known-good commit): {good_rate:.0%} failure rate
- Commit right before culprit: {before_rate:.0%} failure rate
- Culprit commit: {culprit_rate:.0%} failure rate
- Bisection threshold used: {threshold:.0%}
- Preliminary verdict: {verdict}

Diff of the culprit commit:
```diff
{diff}
```

In 2-4 sentences, explain in plain English what in this diff most likely caused the change in failure rate \
(e.g. shared mutable state without a lock, a timing/ordering assumption, a resource leak, a logic bug). \
Be concrete and reference the actual code change. If it looks like a clean deterministic bug rather than \
a concurrency/timing issue, say so plainly."""


def explain(outcome: BisectOutcome, diff: str, threshold: float, api_key: str | None = None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    prompt = PROMPT_TEMPLATE.format(
        sha=outcome.culprit.sha[:12],
        subject=outcome.culprit.subject,
        good_rate=outcome.good_baseline.flake_rate,
        before_rate=outcome.before.result.flake_rate,
        culprit_rate=outcome.culprit.result.flake_rate,
        threshold=threshold,
        verdict=outcome.verdict,
        diff=diff[:6000],
    )

    message = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in message.content if hasattr(block, "text")).strip()
