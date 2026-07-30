"""Run a command N times against a directory and compute a failure rate.

The command is anything a shell can run — a test suite, a build, a script, an
integration probe. Exit code 0 is a pass, anything else is a failure, and the
output of failing runs is captured so the failure modes can be clustered and
explained later.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .failures import FailureMode, cluster

# Enough of the tail to hold a stack trace and the assertion that caused it,
# without dragging a full verbose test log into memory 20 times over.
MAX_CAPTURED_CHARS = 6000

# How much raw output to hold before discarding from the front. Only the tail is
# ever reported, and a chatty suite times `--runs` parallel workers.
CAPTURE_BUFFER_CHARS = 256_000

# After the command exits, how long to keep reading its pipe. Anything still
# holding it open is a process the command spawned and left behind.
ORPHAN_GRACE_SECONDS = 0.5


@dataclass
class Attempt:
    ok: bool
    exit_code: int
    output: str
    timed_out: bool = False


@dataclass
class RunResult:
    passed: int
    failed: int
    runs: int
    failure_outputs: list[str] = field(default_factory=list)
    timeouts: int = 0
    setup_failed: bool = False
    setup_output: str = ""

    @property
    def flake_rate(self) -> float:
        return self.failed / self.runs if self.runs else 0.0

    @property
    def failure_modes(self) -> list[FailureMode]:
        return cluster(self.failure_outputs)


class SetupError(RuntimeError):
    """Raised when a worktree's setup step fails and the caller wants to stop."""


def worker_count_for(runs: int, requested: int | None = None) -> int:
    """How many runs to execute at once.

    Defaults to the core count, capped at `runs` so we never oversubscribe.
    `requested` lets a caller force it down — the N runs share one worktree, so
    a suite that isn't concurrency-safe (fixed ports, a shared scratch file, a
    single test database) needs `--workers 1` or it measures its own contention
    rather than the bug.
    """
    ceiling = max(1, runs)
    if requested is not None:
        return max(1, min(requested, ceiling))
    cores = os.cpu_count() or 4
    return max(1, min(ceiling, cores))


def _tail(text: str, limit: int = MAX_CAPTURED_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "…(truncated)…\n" + text[-limit:]


def _process_group(proc: subprocess.Popen) -> int | None:
    """The child's process group, captured while it is still alive.

    Must be read before the process is reaped: afterwards `os.getpgid` fails,
    and the orphans we most need to kill are exactly the ones that outlive it.
    """
    if os.name != "posix":
        return None
    try:
        return os.getpgid(proc.pid)
    except OSError:
        return None


def _kill_tree(proc: subprocess.Popen, pgid: int | None) -> None:
    """Kill the command *and* anything it spawned.

    A test runner that shells out to a server leaves orphans behind if only the
    direct child is killed, and those orphans hold the ports the next run needs.
    """
    if pgid is not None and pgid != os.getpgid(0):
        try:
            os.killpg(pgid, signal.SIGKILL)
            return
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _drain(stream, chunks: list[str]) -> None:
    """Accumulate the tail of a stream until it closes."""
    total = 0
    try:
        for chunk in iter(lambda: stream.read(8192), ""):
            chunks.append(chunk)
            total += len(chunk)
            while total > CAPTURE_BUFFER_CHARS and len(chunks) > 1:
                total -= len(chunks.pop(0))
    except (ValueError, OSError):
        pass  # pipe closed underneath us; whatever we got is what we report


def run_once(
    cmd: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Attempt:
    """Run `cmd` once and report whether it passed, plus the tail of its output.

    Output is drained on a side thread and the wait is on *process exit*, not on
    the pipe reaching EOF. A suite that starts a dev server and leaves it running
    hands that server a copy of our stdout, so waiting for EOF would block for as
    long as the server lives — forever, at the default timeout.
    """
    popen_kwargs: dict = {}
    if os.name == "posix":
        # own process group, so _kill_tree can take out grandchildren too
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        **popen_kwargs,
    )

    pgid = _process_group(proc)
    chunks: list[str] = []
    reader = threading.Thread(target=_drain, args=(proc.stdout, chunks), daemon=True)
    reader.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc, pgid)
        proc.wait()

    # The command itself is gone. Give its output a moment to land, then stop
    # waiting: a pipe still open belongs to something it orphaned, and that
    # orphan would also hold the ports the next run needs.
    reader.join(ORPHAN_GRACE_SECONDS)
    if reader.is_alive():
        _kill_tree(proc, pgid)
        reader.join(ORPHAN_GRACE_SECONDS)

    # Only safe once the reader has let go: closing a pipe mid-read blocks on
    # the lock that thread is holding, which is the hang we came here to fix.
    if not reader.is_alive():
        try:
            proc.stdout.close()
        except OSError:
            pass

    output = "".join(chunks)
    if timed_out:
        note = f"[flarebisect] command timed out after {timeout:g}s and was killed"
        return Attempt(ok=False, exit_code=-1, output=_tail(output + "\n" + note), timed_out=True)

    code = proc.returncode
    return Attempt(ok=code == 0, exit_code=code, output=_tail(output))


def prepare(
    setup_cmd: str | None,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Attempt | None:
    """Run the one-time setup step for a directory. None if there is none."""
    if not setup_cmd:
        return None
    return run_once(setup_cmd, cwd, env=env, timeout=timeout)


def measure_flake_rate(
    test_cmd: str,
    cwd: Path,
    runs: int,
    setup_cmd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    setup_timeout: float | None = None,
    workers: int | None = None,
) -> RunResult:
    """Prepare `cwd`, then run `test_cmd` `runs` times in parallel.

    If setup fails, every run is recorded as a failure and the result is
    flagged — a commit that can no longer be built is a real signal, but the
    caller needs to be able to tell it apart from a genuinely failing command.
    """
    setup = prepare(setup_cmd, cwd, env=env, timeout=setup_timeout)
    if setup is not None and not setup.ok:
        return RunResult(
            passed=0,
            failed=runs,
            runs=runs,
            failure_outputs=[f"[flarebisect] setup failed: {setup_cmd}\n{setup.output}"],
            setup_failed=True,
            setup_output=setup.output,
        )

    with ThreadPoolExecutor(max_workers=worker_count_for(runs, workers)) as pool:
        attempts = list(pool.map(lambda _: run_once(test_cmd, cwd, env=env, timeout=timeout), range(runs)))

    passed = sum(1 for a in attempts if a.ok)
    return RunResult(
        passed=passed,
        failed=runs - passed,
        runs=runs,
        failure_outputs=[a.output for a in attempts if not a.ok],
        timeouts=sum(1 for a in attempts if a.timed_out),
    )
