import pytest
from ai_router.telemetry_roi import TelemetryROI


def test_telemetry_recording():
    stats_before = TelemetryROI.load_stats()
    initial_cmds = stats_before.total_commands

    TelemetryROI.record_command(
        intent="PREP_AND_EXECUTE",
        prep_used=True,
        raw_context_length=8000,
        pruned_context_tokens=1200,
        duration_ms=450.0,
        is_cache_hit=True,
    )

    stats_after = TelemetryROI.load_stats()
    assert stats_after.total_commands == initial_cmds + 1
    assert stats_after.prep_invocations >= 1
    assert stats_after.dollar_savings_usd > 0.0
