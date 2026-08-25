import pytest
from ai_router.eval_harness import EvalHarness


def test_eval_harness_execution():
    report = EvalHarness.run_eval()
    assert report.total_cases > 0
    assert report.accuracy_percentage >= 75.0
    assert report.avg_latency_ms < 50.0
