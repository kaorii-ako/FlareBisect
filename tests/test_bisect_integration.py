"""End-to-end bisection over a real git repo with a scripted failure rate.

The command is a shell script, not a Python test — the engine must not care
what language anything is written in.
"""

import os
import subprocess

import pytest

from flarebisect.bisect import run_bisect

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses POSIX shell commands")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_repo(tmp_path, rates):
    """A repo whose command fails at a scripted rate, one commit per rate.

    `flake.sh` fails on the first `rate*20` of every 20 runs, counted through a
    lock-protected file, so each commit's measured rate is exact.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@e.st")
    git(repo, "config", "user.name", "test")

    for i, rate in enumerate(rates):
        fails = int(round(rate * 20))
        (repo / "flake.sh").write_text(
            "#!/bin/sh\n"
            # keeps consecutive same-rate commits from being empty diffs
            f"# revision {i}\n"
            "until mkdir .lock 2>/dev/null; do :; done\n"
            "n=$(cat counter 2>/dev/null || echo 0)\n"
            "echo $(( (n+1) % 20 )) > counter\n"
            "rmdir .lock\n"
            f"if [ $((n % 20)) -lt {fails} ]; then echo 'Error: lost update' >&2; exit 1; fi\n"
        )
        os.chmod(repo / "flake.sh", 0o755)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"commit {i} at rate {rate}")
        git(repo, "tag", f"c{i}")

    return repo


def bisect(repo, **kw):
    # counter state must not leak between commits, so each worktree starts clean
    return run_bisect(
        repo=repo, good="c0", bad=f"c{kw.pop('last')}", test_cmd="./flake.sh", runs=20, **kw
    )


def test_finds_the_commit_where_the_rate_jumps(tmp_path):
    # clean, clean, 80% flaky, still flaky
    repo = make_repo(tmp_path, [0.0, 0.0, 0.8, 0.8])
    outcome = bisect(repo, last=3, threshold=0.3)

    assert outcome.culprit_found
    assert outcome.culprit.subject == "commit 2 at rate 0.8"
    assert outcome.verdict == "flakiness regression"


def test_clean_break_is_classified_separately(tmp_path):
    repo = make_repo(tmp_path, [0.0, 0.0, 1.0])
    outcome = bisect(repo, last=2, threshold=0.3)

    assert outcome.culprit.subject == "commit 2 at rate 1.0"
    assert outcome.verdict == "clean break"


def test_inconclusive_when_nothing_crosses_the_threshold(tmp_path):
    # a 10% wobble everywhere, well under a 30% threshold
    repo = make_repo(tmp_path, [0.0, 0.1, 0.1])
    outcome = bisect(repo, last=2, threshold=0.3)

    assert not outcome.culprit_found
    # nothing may be labelled the flare when nothing was implicated
    assert all(m.status != "flare" for m in outcome.measurements)


def test_lower_threshold_finds_the_subtle_regression(tmp_path):
    repo = make_repo(tmp_path, [0.0, 0.0, 0.25, 0.25])
    assert not bisect(repo, last=3, threshold=0.5).culprit_found

    outcome = bisect(repo, last=3, threshold=0.15)
    assert outcome.culprit_found
    assert outcome.culprit.subject == "commit 2 at rate 0.25"


def test_failure_output_reaches_the_outcome(tmp_path):
    repo = make_repo(tmp_path, [0.0, 0.0, 0.8])
    outcome = bisect(repo, last=2, threshold=0.3)

    modes = outcome.failure_modes
    assert modes and "lost update" in modes[0].headline


def test_refuses_a_baseline_that_is_already_fully_broken(tmp_path):
    repo = make_repo(tmp_path, [1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="no working baseline"):
        bisect(repo, last=2, threshold=0.3)


def test_setup_step_runs_in_each_worktree(tmp_path):
    repo = make_repo(tmp_path, [0.0, 0.0, 0.8])
    outcome = run_bisect(
        repo=repo,
        good="c0",
        bad="c2",
        # the command depends on a file only setup creates
        test_cmd="test -f prepared && ./flake.sh",
        setup_cmd="touch prepared",
        runs=20,
        threshold=0.3,
    )
    assert outcome.culprit_found
    assert outcome.culprit.subject == "commit 2 at rate 0.8"


def test_broken_setup_at_a_later_commit_is_flagged_not_hidden(tmp_path):
    repo = make_repo(tmp_path, [0.0, 0.0])
    outcome = run_bisect(
        repo=repo,
        good="c0",
        bad="c1",
        test_cmd="./flake.sh",
        # only the c0 worktree carries the "revision 0" marker, so setup
        # succeeds at the baseline and breaks at c1 — a commit that stops building
        setup_cmd="grep -q 'revision 0' flake.sh",
        runs=4,
        threshold=0.3,
    )
    assert outcome.culprit.result.setup_failed
    assert outcome.verdict == "build break"
    assert outcome.culprit.status == "setup"
