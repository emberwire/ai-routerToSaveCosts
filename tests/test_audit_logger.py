import pytest
from pathlib import Path
from ai_router.audit_logger import AuditLogger
from ai_router.config import get_config


def test_audit_logging():
    AuditLogger.log_event(
        user_prompt="Test secure prompt",
        intent="EXECUTE_ONLY",
        engine="claude",
        prep_invoked=False,
        duration_ms=12.0,
        exit_code=0,
    )
    log_path = get_config().get_audit_log_path()
    assert log_path.exists()
    assert "Test secure prompt" not in log_path.read_text() # Verify SHA256 hashed
    assert "EXECUTE_ONLY" in log_path.read_text()
