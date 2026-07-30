"""The LLM call itself is mocked — what matters is that the evidence we
gathered (failure output, rates, diff) actually reaches the prompt."""

from pathlib import Path

import pytest

from flarebisect import ai_explain
from flarebisect.bisect import BisectOutcome, CommitMeasurement
from flarebisect.diagnose import DiagnoseOutcome
from flarebisect.runner import RunResult

FAILURE = "AssertionError: expected 10, got 9\n  at counter.py:14"


def _measurement(sha, rate, runs=10, outputs=None):
    failed = round(rate * runs)
    return CommitMeasurement(
        sha=sha,
        subject="drop lock in bump()",
        result=RunResult(
            passed=runs - failed,
            failed=failed,
            runs=runs,
            failure_outputs=outputs if outputs is not None else [FAILURE] * failed,
        ),
        position=1,
    )


def _bisect_outcome():
    culprit = _measurement("9c1f88aa", 0.8)
    before = _measurement("4f9e2100", 0.0)
    return BisectOutcome(
        culprit=culprit,
        before=before,
        good_baseline=before.result,
        bad_baseline=culprit.result,
        verdict="flakiness regression",
        measurements=[before, culprit],
        total_commits=2,
        runs=10,
        workers=4,
        elapsed_seconds=1.0,
        command="npm test",
    )


@pytest.fixture
def captured(monkeypatch):
    box = {}

    def fake_complete(cfg, prompt, max_tokens=300):
        box["prompt"] = prompt
        box["max_tokens"] = max_tokens
        return "shared counter mutated without a lock"

    monkeypatch.setattr(ai_explain, "complete", fake_complete)
    return box


class TestExplain:
    def test_prompt_carries_the_command(self, captured):
        ai_explain.explain(_bisect_outcome(), "diff --git a/x b/x", 0.3, None)
        assert "npm test" in captured["prompt"]

    def test_prompt_carries_the_failure_output(self, captured):
        ai_explain.explain(_bisect_outcome(), "diff --git a/x b/x", 0.3, None)
        assert "AssertionError: expected 10, got 9" in captured["prompt"]

    def test_prompt_carries_the_diff(self, captured):
        ai_explain.explain(_bisect_outcome(), "diff --git a/counter.py", 0.3, None)
        assert "diff --git a/counter.py" in captured["prompt"]

    def test_prompt_carries_the_rates(self, captured):
        ai_explain.explain(_bisect_outcome(), "d", 0.3, None)
        assert "0%" in captured["prompt"] and "80%" in captured["prompt"]

    def test_huge_diff_is_truncated(self, captured):
        ai_explain.explain(_bisect_outcome(), "x" * 50_000, 0.3, None)
        assert len(captured["prompt"]) < 30_000

    def test_works_when_there_is_no_failure_output(self, captured):
        outcome = _bisect_outcome()
        outcome.culprit.result.failure_outputs = []
        ai_explain.explain(outcome, "d", 0.3, None)
        assert "failure mode" not in captured["prompt"]

    def test_returns_the_model_text(self, captured):
        assert ai_explain.explain(_bisect_outcome(), "d", 0.3, None).startswith("shared counter")


class TestExplainFailures:
    def _diag(self, outputs):
        result = RunResult(passed=0, failed=len(outputs), runs=len(outputs), failure_outputs=outputs)
        return DiagnoseOutcome(
            command="./deploy-check.sh",
            workdir=Path("/tmp/x"),
            ref=None,
            result=result,
            modes=result.failure_modes,
            runs=len(outputs),
            workers=4,
            elapsed_seconds=1.0,
        )

    def test_prompt_lists_each_failure_mode(self, captured):
        ai_explain.explain_failures(
            self._diag(["Error: connection refused", "panic: nil map write"]), None
        )
        assert "connection refused" in captured["prompt"]
        assert "nil map write" in captured["prompt"]

    def test_prompt_carries_the_command(self, captured):
        ai_explain.explain_failures(self._diag(["boom"]), None)
        assert "./deploy-check.sh" in captured["prompt"]

    def test_prompt_reports_the_mode_count(self, captured):
        ai_explain.explain_failures(self._diag(["Error: a", "panic: b", "Error: a"]), None)
        assert "distinct failure modes: 2" in captured["prompt"]

    def test_only_the_top_modes_are_included(self, captured):
        outputs = [f"Error{i}: distinct thing {i}" for i in range(10)]
        ai_explain.explain_failures(self._diag(outputs), None)
        assert "rarer failure modes omitted" in captured["prompt"]
