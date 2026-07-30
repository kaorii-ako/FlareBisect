"""Diagnose a flaky command in place, with no commit range to bisect.

Bisection answers "which commit did this?" — but that assumes you know a
commit where the command was healthy. Often you don't: the flake has been
there as long as anyone remembers, or it only shows up on this machine, or
it isn't even in a git repo.

Diagnose mode skips history entirely. It runs the command N times right where
it stands, clusters the failures into distinct modes, and hands the LLM the
real error text.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import git_ops
from .failures import FailureMode
from .runner import RunResult, measure_flake_rate, worker_count_for
from .toolchains import Plan


@dataclass
class DiagnoseOutcome:
    command: str
    workdir: Path
    ref: str | None
    result: RunResult
    modes: list[FailureMode]
    runs: int
    workers: int
    elapsed_seconds: float
    plan: Plan | None = None

    @property
    def flake_rate(self) -> float:
        return self.result.flake_rate

    @property
    def verdict(self) -> str:
        rate = self.result.flake_rate
        several = len(self.modes) > 1
        if self.result.setup_failed:
            return "setup failed"
        if rate == 0.0:
            return "no failures reproduced"
        if rate >= 1.0:
            # Always failing, but not necessarily always the *same* failure —
            # several modes means more than one thing is broken.
            return "always fails, in several ways" if several else "deterministic failure"
        if several:
            return "flaky — multiple failure modes"
        return "flaky — single failure mode"


def run_diagnose(
    workdir: Path,
    command: str,
    runs: int = 20,
    repo: Path | None = None,
    ref: str | None = None,
    setup_cmd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    setup_timeout: float | None = None,
    workers: int | None = None,
    plan: Plan | None = None,
) -> DiagnoseOutcome:
    """Run `command` `runs` times and group how it failed.

    With `ref`, the command runs against an isolated worktree at that commit;
    without one it runs in `workdir` as-is, so this works outside git too.
    """
    started = time.perf_counter()

    if ref is not None:
        if repo is None:
            raise ValueError("a repo is required to diagnose at a specific ref")
        sha = git_ops.resolve_sha(repo, ref)
        wt = git_ops.add_worktree(repo, sha)
        try:
            result = measure_flake_rate(
                command, wt.path, runs, setup_cmd=setup_cmd, env=env,
                timeout=timeout, setup_timeout=setup_timeout, workers=workers,
            )
        finally:
            git_ops.remove_worktree(repo, wt)
        target = workdir
    else:
        result = measure_flake_rate(
            command, workdir, runs, setup_cmd=setup_cmd, env=env,
            timeout=timeout, setup_timeout=setup_timeout, workers=workers,
        )
        target = workdir

    return DiagnoseOutcome(
        command=command,
        workdir=target,
        ref=ref,
        result=result,
        modes=result.failure_modes,
        runs=runs,
        workers=worker_count_for(runs, workers),
        elapsed_seconds=time.perf_counter() - started,
        plan=plan,
    )
