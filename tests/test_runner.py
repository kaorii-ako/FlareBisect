import os
import sys
import time

import pytest

from flarebisect.runner import measure_flake_rate, run_once, worker_count_for

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX shell commands")


def test_run_once_passes_on_zero_exit(tmp_path):
    assert run_once("true", tmp_path).ok


def test_run_once_fails_on_nonzero_exit(tmp_path):
    attempt = run_once("exit 3", tmp_path)
    assert not attempt.ok
    assert attempt.exit_code == 3


def test_run_once_captures_stdout_and_stderr(tmp_path):
    attempt = run_once("echo out; echo err >&2", tmp_path)
    assert "out" in attempt.output
    assert "err" in attempt.output


def test_run_once_kills_a_hung_command(tmp_path):
    attempt = run_once("sleep 30", tmp_path, timeout=0.5)
    assert not attempt.ok
    assert attempt.timed_out
    assert "timed out" in attempt.output


class TestOrphanedProcesses:
    """A suite that leaves a server running hands it a copy of our stdout.

    Waiting for the pipe to reach EOF would then block for as long as that
    server lives, so the wait must be on process exit instead.
    """

    def test_returns_promptly_when_a_child_outlives_the_command(self, tmp_path):
        started = time.perf_counter()
        attempt = run_once("(sleep 30 &) ; echo done", tmp_path)
        elapsed = time.perf_counter() - started

        assert attempt.ok
        assert elapsed < 5, f"blocked {elapsed:.1f}s on an orphan holding the pipe"

    def test_output_before_the_orphan_is_still_captured(self, tmp_path):
        assert "done" in run_once("(sleep 30 &) ; echo done", tmp_path).output

    def test_the_orphan_is_killed_not_merely_abandoned(self, tmp_path):
        # left alive, it would hold the ports and files the next run needs
        marker = tmp_path / "orphan_ran"
        run_once(f"(sleep 2; touch {marker}) & echo started", tmp_path)
        time.sleep(2.5)
        assert not marker.exists()

    def test_timeout_still_applies_with_an_orphan_present(self, tmp_path):
        started = time.perf_counter()
        attempt = run_once("(sleep 30 &) ; sleep 30", tmp_path, timeout=0.5)
        assert attempt.timed_out
        assert time.perf_counter() - started < 5


def test_output_is_capped_but_keeps_the_tail(tmp_path):
    attempt = run_once("seq 1 200000", tmp_path)
    assert len(attempt.output) < 20_000
    assert attempt.output.rstrip().endswith("200000")


def test_run_once_passes_env_through(tmp_path):
    env = dict(os.environ, FLAREBISECT_MARKER="present")
    assert "present" in run_once("echo $FLAREBISECT_MARKER", tmp_path, env=env).output


def test_measure_all_passing(tmp_path):
    result = measure_flake_rate("true", tmp_path, runs=4)
    assert result.flake_rate == 0.0
    assert result.failure_outputs == []


def test_measure_all_failing(tmp_path):
    result = measure_flake_rate("echo boom >&2; exit 1", tmp_path, runs=4)
    assert result.flake_rate == 1.0
    assert len(result.failure_outputs) == 4
    assert all("boom" in out for out in result.failure_outputs)


def test_measure_runs_setup_first(tmp_path):
    # setup writes the file the command then requires
    result = measure_flake_rate(
        "test -f ready", tmp_path, runs=3, setup_cmd="touch ready"
    )
    assert result.flake_rate == 0.0


def test_setup_failure_is_flagged_not_silent(tmp_path):
    result = measure_flake_rate("true", tmp_path, runs=5, setup_cmd="echo nope >&2; exit 1")
    assert result.setup_failed
    assert result.flake_rate == 1.0
    assert "nope" in result.setup_output


def test_setup_runs_once_not_per_run(tmp_path):
    counter = tmp_path / "count"
    measure_flake_rate("true", tmp_path, runs=6, setup_cmd=f"echo x >> {counter}")
    assert counter.read_text().count("x") == 1


def test_timeouts_are_counted(tmp_path):
    result = measure_flake_rate("sleep 30", tmp_path, runs=2, timeout=0.5)
    assert result.timeouts == 2
    assert result.flake_rate == 1.0


def test_failure_modes_are_clustered_from_captured_output(tmp_path):
    script = tmp_path / "flaky.sh"
    script.write_text("#!/bin/sh\necho 'AssertionError: expected 1 got 2' >&2\nexit 1\n")
    script.chmod(0o755)
    result = measure_flake_rate(str(script), tmp_path, runs=3)
    modes = result.failure_modes
    assert len(modes) == 1
    assert modes[0].count == 3
    assert "AssertionError" in modes[0].headline


def test_worker_count_never_exceeds_cores():
    assert worker_count_for(1000) <= (os.cpu_count() or 4)


def test_worker_count_never_zero():
    assert worker_count_for(0) == 1


def test_run_once_works_with_any_interpreter(tmp_path):
    # the point of the rewrite: the command is arbitrary, not pytest-shaped
    attempt = run_once(f'{sys.executable} -c "raise SystemExit(0)"', tmp_path)
    assert attempt.ok
