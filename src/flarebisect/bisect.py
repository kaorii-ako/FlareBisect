"""Flake-rate bisection: binary search over commits for the point where the
flake rate jumps by >= threshold relative to the known-good baseline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import git_ops
from .runner import RunResult, measure_flake_rate, worker_count_for


@dataclass
class CommitMeasurement:
    sha: str
    subject: str
    result: RunResult
    position: int  # -1 = good baseline, 0..n-1 = index within the good..bad range
    status: str = ""  # filled in once the culprit is known: good/stable/wobbling/flare/bad


@dataclass
class BisectOutcome:
    culprit: CommitMeasurement
    before: CommitMeasurement  # last known-good-ish measurement (parent side)
    good_baseline: RunResult
    bad_baseline: RunResult
    verdict: str  # "clean break" | "flakiness regression"
    measurements: list[CommitMeasurement]  # every distinct commit measured, in range order
    total_commits: int
    runs: int
    workers: int
    elapsed_seconds: float


def _measure(repo: Path, sha: str, test_cmd: str, runs: int, position: int) -> CommitMeasurement:
    wt = git_ops.add_worktree(repo, sha)
    try:
        result = measure_flake_rate(test_cmd, wt.path, runs)
    finally:
        git_ops.remove_worktree(repo, wt)
    return CommitMeasurement(
        sha=sha,
        subject=git_ops.commit_subject(repo, sha),
        result=result,
        position=position,
    )


def classify(good_rate: float, culprit_rate: float) -> str:
    if culprit_rate >= 0.9 and good_rate <= 0.1:
        return "clean break"
    return "flakiness regression"


def status_label(rate: float, is_first: bool, is_last: bool, is_culprit: bool) -> str:
    if is_culprit:
        return "flare"
    if is_last:
        return "bad"
    if rate <= 0.0:
        return "good" if is_first else "stable"
    return "wobbling"


def run_bisect(
    repo: Path,
    good: str,
    bad: str,
    test_cmd: str,
    runs: int = 5,
    threshold: float = 0.3,
    on_measure: Callable[[str, CommitMeasurement], None] | None = None,
) -> BisectOutcome:
    started = time.perf_counter()

    good_sha = git_ops.resolve_sha(repo, good)
    bad_sha = git_ops.resolve_sha(repo, bad)

    good_m = _measure(repo, good_sha, test_cmd, runs, position=-1)
    if on_measure:
        on_measure("good", good_m)

    commits = git_ops.commit_list(repo, good_sha, bad_sha)
    if not commits:
        raise ValueError("no commits between good and bad")

    baseline_rate = good_m.result.flake_rate

    cache: dict[str, CommitMeasurement] = {}

    def measure_idx(idx: int) -> CommitMeasurement:
        sha = commits[idx]
        if sha not in cache:
            m = _measure(repo, sha, test_cmd, runs, position=idx)
            cache[sha] = m
            if on_measure:
                on_measure(f"candidate[{idx}]", m)
        return cache[sha]

    bad_m = measure_idx(len(commits) - 1)

    lo, hi = 0, len(commits) - 1
    culprit_idx = hi  # fall back to bad commit if search never narrows
    culprit_measurement = bad_m

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

    last_idx = len(commits) - 1
    ordered = [good_m] + [cache[sha] for sha in commits if sha in cache]
    for m in ordered:
        m.status = status_label(
            m.result.flake_rate,
            is_first=(m.position == -1),
            is_last=(m.position == last_idx),
            is_culprit=(m.sha == culprit_measurement.sha),
        )

    return BisectOutcome(
        culprit=culprit_measurement,
        before=before_measurement,
        good_baseline=good_m.result,
        bad_baseline=bad_m.result,
        verdict=verdict,
        measurements=ordered,
        total_commits=len(commits),
        runs=runs,
        workers=worker_count_for(runs),
        elapsed_seconds=time.perf_counter() - started,
    )
