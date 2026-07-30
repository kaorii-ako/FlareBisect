"""Rendering tests.

The console renders markup, so any user-controlled string reaching it must be
escaped — otherwise `pytest -k "test[1]"` displays as `pytest -k "test"` and we
show the user a command we did not run.
"""

import io

import pytest
from rich.console import Console

from flarebisect import report
from flarebisect.bisect import BisectOutcome, CommitMeasurement
from flarebisect.diagnose import DiagnoseOutcome
from flarebisect.failures import cluster
from flarebisect.runner import RunResult
from flarebisect.toolchains import BY_NAME, Plan

BRACKETS = 'pytest -k "test[1] and not [slow]" [/] [bold red]'


@pytest.fixture
def rendered(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr(report, "console", Console(file=buffer, width=200, no_color=True, highlight=False))
    return buffer


def _plan(command=BRACKETS, setup=None, toolchain=None):
    return Plan(
        command=command,
        setup=setup,
        toolchain=toolchain,
        command_source="flag",
        setup_source="flag" if setup else "none",
    )


def _measurement(sha="abc1234", rate=0.5, runs=10, outputs=None, subject="a commit"):
    failed = int(rate * runs)
    return CommitMeasurement(
        sha=sha,
        subject=subject,
        result=RunResult(
            passed=runs - failed,
            failed=failed,
            runs=runs,
            failure_outputs=outputs if outputs is not None else ["boom"] * failed,
        ),
        position=0,
    )


class TestMarkupEscaping:
    def test_command_with_brackets_is_shown_verbatim(self, rendered):
        report.print_plan(_plan())
        assert 'test[1] and not [slow]' in rendered.getvalue()

    def test_setup_with_brackets_is_shown_verbatim(self, rendered):
        report.print_plan(_plan(command="x", setup="make ARGS=[a,b]"))
        assert "ARGS=[a,b]" in rendered.getvalue()

    def test_error_message_with_brackets_survives(self, rendered):
        report.print_error("boom [notastyle] here")
        assert "[notastyle]" in rendered.getvalue()

    def test_failure_headline_with_brackets_survives(self, rendered):
        modes = cluster(["Error: bad token [EOF] at line 3"])
        report.print_failure_modes(modes, 1)
        assert "[EOF]" in rendered.getvalue()

    def test_diagnose_ref_with_brackets_survives(self, rendered):
        result = RunResult(passed=1, failed=0, runs=1)
        outcome = DiagnoseOutcome(
            command="true",
            workdir=".",
            ref="refs/[weird]/tag",
            result=result,
            modes=[],
            runs=1,
            workers=1,
            elapsed_seconds=0.1,
        )
        report.print_diagnose_summary(outcome)
        assert "[weird]" in rendered.getvalue()

    def test_commit_subject_with_brackets_survives(self, rendered):
        outcome = _outcome(subject="fix: handle [] in parser")
        report.print_result(outcome, 0.3)
        assert "[]" in rendered.getvalue()


def _outcome(culprit_found=True, subject="a commit", measurements=None):
    culprit = _measurement(rate=0.8, subject=subject)
    before = _measurement(sha="def5678", rate=0.0)
    return BisectOutcome(
        culprit=culprit,
        before=before,
        good_baseline=before.result,
        bad_baseline=culprit.result,
        verdict="flakiness regression",
        measurements=measurements or [before, culprit],
        total_commits=2,
        runs=10,
        workers=4,
        elapsed_seconds=1.0,
        command="npm test",
        culprit_found=culprit_found,
    )


class TestInconclusiveRendering:
    def test_says_inconclusive_and_names_no_culprit(self, rendered):
        report.print_result(_outcome(culprit_found=False), 0.3)
        text = rendered.getvalue()
        assert "inconclusive" in text
        assert "culprit found" not in text

    def test_suggests_a_threshold_below_the_peak_move(self, rendered):
        report.print_result(_outcome(culprit_found=False), 0.3)
        assert "--threshold" in rendered.getvalue()

    def test_normal_result_still_names_the_culprit(self, rendered):
        report.print_result(_outcome(), 0.3)
        assert "culprit found" in rendered.getvalue()


class TestPluralisation:
    def test_single_worker_is_singular(self, rendered):
        report.print_progress_line(total_commits=1, runs=5, workers=1)
        text = rendered.getvalue()
        assert "1 worker)" in text
        assert "1 commit " in text

    def test_many_workers_are_plural(self, rendered):
        report.print_progress_line(total_commits=3, runs=5, workers=8)
        assert "8 workers)" in rendered.getvalue()


class TestRobustRendering:
    def test_empty_failure_modes_render_nothing(self, rendered):
        report.print_failure_modes([], 0)
        assert rendered.getvalue() == ""

    def test_zero_total_failures_does_not_divide_by_zero(self, rendered):
        report.print_failure_modes(cluster(["boom"]), 0)
        assert "boom" in rendered.getvalue()

    def test_table_of_one_measurement(self, rendered):
        report.print_table([_measurement()])
        assert "abc1234" in rendered.getvalue()

    def test_plan_with_detected_toolchain_names_it(self, rendered):
        report.print_plan(_plan(command="go test ./...", toolchain=BY_NAME["go"]))
        assert "go" in rendered.getvalue()

    def test_excerpt_of_a_mode_renders(self, rendered):
        report.print_excerpt(cluster(["line one\nAssertionError: nope\nline three"])[0])
        assert "AssertionError" in rendered.getvalue()
