"""Flake-rate bisection: binary search over commits for the point where the
failure rate jumps by >= threshold relative to the known-good baseline.

The command under bisection is arbitrary — a test suite, a build, a script —
so each candidate worktree is prepared with the toolchain's setup step before
it's measured."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import git_ops
from .failures import FailureMode, cluster
from .runner import RunResult, measure_flake_rate, worker_count_for
from .toolchains import Plan


@dataclass
class CommitMeasurement:
    sha: str
    subject: str
    result: RunResult
    position: int  # -1 = good baseline, 0..n-1 = index within the good..bad range
    status: str = ""  # filled in once the culprit is known: good/stable/wobbling/flare/bad/setup


@dataclass
class BisectOutcome:
    culprit: CommitMeasurement
    before: CommitMeasurement  # last known-good-ish measurement (parent side)
    good_baseline: RunResult
    bad_baseline: RunResult
    verdict: str  # "clean break" | "flakiness regression" | "build break"
    measurements: list[CommitMeasurement]  # every distinct commit measured, in range order
    total_commits: int
    runs: int
    workers: int
    elapsed_seconds: float
    command: str = ""
    plan: Plan | None = None
    # False when no commit's failure rate ever crossed the threshold. The
    # search then has nothing to point at, and `culprit` is only the `bad`
    # endpoint standing in — saying so beats blaming an innocent commit.
    culprit_found: bool = True

    @property
    def focus(self) -> CommitMeasurement:
        """The measurement worth showing failure output for.

        The culprit when we found one; otherwise the worst commit measured,
        since the `bad` endpoint standing in for a culprit may not even be the
        one that failed most.
        """
        if self.culprit_found:
            return self.culprit
        return max(self.measurements, key=lambda m: m.result.flake_rate)

    @property
    def failure_modes(self) -> list[FailureMode]:
        """Distinct ways the command failed at the commit under suspicion."""
        return cluster(self.focus.result.failure_outputs)


def _measure(
    repo: Path,
    sha: str,
    test_cmd: str,
    runs: int,
    position: int,
    setup_cmd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    setup_timeout: float | None = None,
    workers: int | None = None,
) -> CommitMeasurement:
    wt = git_ops.add_worktree(repo, sha)
    try:
        result = measure_flake_rate(
            test_cmd,
            wt.path,
            runs,
            setup_cmd=setup_cmd,
            env=env,
            timeout=timeout,
            setup_timeout=setup_timeout,
            workers=workers,
        )
    finally:
        git_ops.remove_worktree(repo, wt)
    return CommitMeasurement(
        sha=sha,
        subject=git_ops.commit_subject(repo, sha),
        result=result,
        position=position,
    )


def classify(good_rate: float, culprit_rate: float, setup_failed: bool = False) -> str:
    if setup_failed:
        return "build break"
    if culprit_rate >= 0.9 and good_rate <= 0.1:
        return "clean break"
    return "flakiness regression"


def status_label(
    rate: float,
    is_first: bool,
    is_last: bool,
    is_culprit: bool,
    setup_failed: bool = False,
) -> str:
    if setup_failed:
        return "setup"
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
    setup_cmd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    setup_timeout: float | None = None,
    workers: int | None = None,
    plan: Plan | None = None,
) -> BisectOutcome:
    started = time.perf_counter()

    good_sha = git_ops.resolve_sha(repo, good)
    bad_sha = git_ops.resolve_sha(repo, bad)

    def measure_at(sha: str, position: int) -> CommitMeasurement:
        return _measure(
            repo,
            sha,
            test_cmd,
            runs,
            position=position,
            setup_cmd=setup_cmd,
            env=env,
            timeout=timeout,
            setup_timeout=setup_timeout,
            workers=workers,
        )

    good_m = measure_at(good_sha, position=-1)
    if on_measure:
        on_measure("good", good_m)

    if good_m.result.setup_failed:
        # Every commit would measure as 100% failing, so the search would be
        # meaningless. Almost always a wrong or missing --setup.
        raise ValueError(
            f"setup failed at the known-good commit ({good_sha[:7]}), so there is no "
            f"working baseline to compare against.\n\nsetup command: {setup_cmd}\n\n"
            f"{good_m.result.setup_output[-1500:]}"
        )

    if good_m.result.flake_rate >= 1.0:
        # No commit can ever "jump" above a baseline that is already at 100%, so
        # the search would silently fall through and blame the last commit. This
        # is the confidently-wrong answer flarebisect exists to avoid, so stop.
        modes = cluster(good_m.result.failure_outputs)
        detail = f"\n\nmost common failure:\n{modes[0].headline}" if modes else ""
        raise ValueError(
            f"the command failed on all {runs} runs at the known-good commit "
            f"({good_sha[:7]}), so there is no working baseline to bisect against.\n\n"
            f"command: {test_cmd}\n"
            f"This usually means the command itself is wrong for this repo, or a build "
            f"step is missing — try --setup, or check that --good is really good."
            f"{detail}"
        )

    commits = git_ops.commit_list(repo, good_sha, bad_sha)
    if not commits:
        raise ValueError("no commits between good and bad")

    baseline_rate = good_m.result.flake_rate

    cache: dict[str, CommitMeasurement] = {}

    def measure_idx(idx: int) -> CommitMeasurement:
        sha = commits[idx]
        if sha not in cache:
            m = measure_at(sha, position=idx)
            cache[sha] = m
            if on_measure:
                on_measure(f"candidate[{idx}]", m)
        return cache[sha]

    bad_m = measure_idx(len(commits) - 1)

    lo, hi = 0, len(commits) - 1
    culprit_idx = hi  # fall back to bad commit if search never narrows
    culprit_measurement = bad_m
    culprit_found = False

    while lo <= hi:
        mid = (lo + hi) // 2
        m = measure_idx(mid)
        jumped = (m.result.flake_rate - baseline_rate) >= threshold
        if jumped:
            culprit_idx = mid
            culprit_measurement = m
            culprit_found = True
            hi = mid - 1
        else:
            lo = mid + 1

    before_measurement = measure_idx(culprit_idx - 1) if culprit_idx > 0 else good_m

    verdict = classify(
        before_measurement.result.flake_rate,
        culprit_measurement.result.flake_rate,
        setup_failed=culprit_measurement.result.setup_failed,
    )

    last_idx = len(commits) - 1
    ordered = [good_m] + [cache[sha] for sha in commits if sha in cache]
    for m in ordered:
        m.status = status_label(
            m.result.flake_rate,
            is_first=(m.position == -1),
            is_last=(m.position == last_idx),
            is_culprit=culprit_found and (m.sha == culprit_measurement.sha),
            setup_failed=m.result.setup_failed,
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
        workers=worker_count_for(runs, workers),
        elapsed_seconds=time.perf_counter() - started,
        command=test_cmd,
        plan=plan,
        culprit_found=culprit_found,
    )
