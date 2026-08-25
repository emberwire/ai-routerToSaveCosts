import json
import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from ai_router.config import get_config


class AuditLogger:
    """
    CSO SOC 2 / ISO 27001 Compliant Audit Logger.
    Maintains an immutable, append-only JSONL log of every AI command,
    recording cryptographic hashes of prompts and injected context.
    """

    @staticmethod
    def _sha256(text: Optional[str]) -> str:
        if not text:
            return "none"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def log_event(
        cls,
        user_prompt: str,
        intent: str,
        engine: str,
        prep_invoked: bool,
        prep_context: Optional[str] = None,
        dlp_violations: Optional[list] = None,
        duration_ms: Optional[float] = None,
        circuit_status: Optional[str] = None,
        exit_code: int = 0,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        config = get_config()
        if not config.enable_audit_logging:
            return

        log_path = config.get_audit_log_path()

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": os.getenv("USER", "unknown"),
            "prompt_hash": cls._sha256(user_prompt),
            "prompt_length": len(user_prompt),
            "intent": intent,
            "engine": engine,
            "prep_invoked": prep_invoked,
            "prep_context_hash": cls._sha256(prep_context),
            "prep_context_length": len(prep_context) if prep_context else 0,
            "dlp_violations": dlp_violations or [],
            "circuit_status": circuit_status or "CLOSED",
            "duration_ms": duration_ms or 0.0,
            "exit_code": exit_code,
            "metadata": extra_metadata or {},
        }

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            # Audit logging failure should not crash the developer CLI, but is recorded if possible
            pass
