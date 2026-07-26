"""Run a test command N times against a worktree and compute a flake rate."""

from __future__ import annotations

import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    passed: int
    failed: int
    runs: int

    @property
    def flake_rate(self) -> float:
        return self.failed / self.runs if self.runs else 0.0


def _one_run(test_cmd: str, cwd: Path) -> bool:
    result = subprocess.run(
        test_cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def measure_flake_rate(test_cmd: str, cwd: Path, runs: int) -> RunResult:
    with ThreadPoolExecutor(max_workers=runs) as pool:
        outcomes = list(pool.map(lambda _: _one_run(test_cmd, cwd), range(runs)))
    passed = sum(outcomes)
    failed = runs - passed
    return RunResult(passed=passed, failed=failed, runs=runs)
