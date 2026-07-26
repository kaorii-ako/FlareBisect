"""Flake-rate bisection: binary search over commits for the point where the
flake rate jumps by >= threshold relative to the known-good baseline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import git_ops
from .runner import RunResult, measure_flake_rate


@dataclass
class CommitMeasurement:
    sha: str
    subject: str
    result: RunResult


@dataclass
class BisectOutcome:
    culprit: CommitMeasurement
    before: CommitMeasurement  # last known-good-ish measurement (parent side)
    good_baseline: RunResult
    bad_baseline: RunResult
    verdict: str  # "clean break" | "flakiness regression"


def _measure(repo: Path, sha: str, test_cmd: str, runs: int) -> CommitMeasurement:
    wt = git_ops.add_worktree(repo, sha)
    try:
        result = measure_flake_rate(test_cmd, wt.path, runs)
    finally:
        git_ops.remove_worktree(repo, wt)
    return CommitMeasurement(
        sha=sha,
        subject=git_ops.commit_subject(repo, sha),
        result=result,
    )


def classify(good_rate: float, culprit_rate: float) -> str:
    if culprit_rate >= 0.9 and good_rate <= 0.1:
        return "clean break"
    return "flakiness regression"


def run_bisect(
    repo: Path,
    good: str,
    bad: str,
    test_cmd: str,
    runs: int = 5,
    threshold: float = 0.3,
    on_measure: Callable[[str, CommitMeasurement], None] | None = None,
) -> BisectOutcome:
    good_sha = git_ops.resolve_sha(repo, good)
    bad_sha = git_ops.resolve_sha(repo, bad)

    good_m = _measure(repo, good_sha, test_cmd, runs)
    if on_measure:
        on_measure("baseline-good", good_m)

    bad_m = _measure(repo, bad_sha, test_cmd, runs)
    if on_measure:
        on_measure("baseline-bad", bad_m)

    commits = git_ops.commit_list(repo, good_sha, bad_sha)
    if not commits:
        raise ValueError("no commits between good and bad")

    baseline_rate = good_m.result.flake_rate

    lo, hi = 0, len(commits) - 1
    culprit_idx = hi  # fall back to bad commit if search never narrows
    culprit_measurement = bad_m
    before_measurement = good_m

    cache: dict[str, CommitMeasurement] = {}

    def measure_idx(idx: int) -> CommitMeasurement:
        sha = commits[idx]
        if sha not in cache:
            m = _measure(repo, sha, test_cmd, runs)
            cache[sha] = m
            if on_measure:
                on_measure(f"candidate[{idx}]", m)
        return cache[sha]

    while lo <= hi:
        mid = (lo + hi) // 2
        m = measure_idx(mid)
        jumped = (m.result.flake_rate - baseline_rate) >= threshold
        if jumped:
            culprit_idx = mid
            culprit_measurement = m
            hi = mid - 1
        else:
            lo = mid + 1

    before_measurement = measure_idx(culprit_idx - 1) if culprit_idx > 0 else good_m

    verdict = classify(before_measurement.result.flake_rate, culprit_measurement.result.flake_rate)

    return BisectOutcome(
        culprit=culprit_measurement,
        before=before_measurement,
        good_baseline=good_m.result,
        bad_baseline=bad_m.result,
        verdict=verdict,
    )
