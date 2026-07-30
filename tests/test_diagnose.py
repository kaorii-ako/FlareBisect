import os

import pytest

from flarebisect.diagnose import run_diagnose

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX shell commands")


def test_clean_command_reports_no_failures(tmp_path):
    outcome = run_diagnose(tmp_path, "true", runs=4)
    assert outcome.result.failed == 0
    assert outcome.verdict == "no failures reproduced"
    assert outcome.modes == []


def test_always_failing_command_is_deterministic(tmp_path):
    outcome = run_diagnose(tmp_path, "exit 1", runs=4)
    assert outcome.verdict == "deterministic failure"
    assert outcome.flake_rate == 1.0


# `mkdir` is atomic on every POSIX filesystem, so this hands each parallel run a
# distinct, predictable turn number — no reliance on PID parity or scheduling.
TICKET = (
    "#!/bin/sh\n"
    "until mkdir .lock 2>/dev/null; do :; done\n"
    "n=$(cat counter 2>/dev/null || echo 0)\n"
    "echo $((n+1)) > counter\n"
    "rmdir .lock\n"
)


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(TICKET + body)
    path.chmod(0o755)
    return path


def test_single_failure_mode_flaky(tmp_path):
    # fails on exactly half the runs, always the same way
    script = _script(
        tmp_path,
        "flaky.sh",
        "if [ $((n % 2)) -eq 0 ]; then echo 'Error: connection refused' >&2; exit 1; fi\n",
    )
    outcome = run_diagnose(tmp_path, str(script), runs=6)
    assert outcome.result.failed == 3
    assert len(outcome.modes) == 1
    assert "connection refused" in outcome.modes[0].headline
    assert outcome.verdict == "flaky — single failure mode"


def test_multiple_failure_modes_are_reported(tmp_path):
    script = _script(
        tmp_path,
        "two_bugs.sh",
        "if [ $((n % 3)) -eq 0 ]; then echo 'AssertionError: expected 1' >&2; exit 1; fi\n"
        "if [ $((n % 3)) -eq 1 ]; then echo 'panic: nil map write' >&2; exit 1; fi\n",
    )
    outcome = run_diagnose(tmp_path, str(script), runs=9)
    assert outcome.result.failed == 6
    assert len(outcome.modes) == 2
    assert outcome.verdict == "flaky — multiple failure modes"
    assert {m.count for m in outcome.modes} == {3}


def test_always_failing_several_ways(tmp_path):
    script = _script(
        tmp_path,
        "both.sh",
        "if [ $((n % 2)) -eq 0 ]; then echo 'panic: nil map write' >&2; else "
        "echo 'AssertionError: expected 1' >&2; fi\nexit 1\n",
    )
    outcome = run_diagnose(tmp_path, str(script), runs=6)
    assert outcome.flake_rate == 1.0
    assert outcome.verdict == "always fails, in several ways"


def test_setup_failure_is_surfaced(tmp_path):
    outcome = run_diagnose(tmp_path, "true", runs=3, setup_cmd="exit 1")
    assert outcome.verdict == "setup failed"
    assert outcome.result.setup_failed


def test_ref_without_repo_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="repo is required"):
        run_diagnose(tmp_path, "true", runs=2, ref="HEAD")


def test_works_outside_a_git_repo(tmp_path):
    # no .git anywhere — diagnose must not need one
    assert not (tmp_path / ".git").exists()
    outcome = run_diagnose(tmp_path, "exit 1", runs=2)
    assert outcome.result.failed == 2
