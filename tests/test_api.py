import io
import json
import os
import stat
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from ai_router import AIRouter, ClassificationResult, RouteResult, RouterEvent
from ai_router.config import get_config
from ai_router.engines.base import EngineStatus, ExecutionResult
from ai_router.engines.gemini_engine import GeminiExecutionEngine


def _router(tmp_path: Path, **overrides) -> AIRouter:
    """Builds an AIRouter whose audit/telemetry/cache files stay under tmp_path
    instead of touching the real ~/.ai_router directory."""
    overrides.setdefault("user_config_dir", tmp_path / "user_config")
    overrides.setdefault("local_cache_dir", tmp_path / "local_cache")
    return AIRouter(**overrides)


def test_route_mock_returns_populated_result(tmp_path):
    router = _router(tmp_path)
    result = router.route("Build a login page", mock=True)

    assert isinstance(result, RouteResult)
    assert result.executed is True
    assert result.exit_code == 0
    assert result.engine == "claude"
    assert result.model
    assert result.output_text != ""
    assert result.status == "success"


def test_route_prints_nothing(tmp_path):
    router = _router(tmp_path)
    out, err = io.StringIO(), io.StringIO()

    with redirect_stdout(out), redirect_stderr(err):
        result = router.route("Integrate Stripe Checkout webhook", mock=True)

    assert result.exit_code == 0
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_on_event_order_for_prep_and_execute(tmp_path):
    router = _router(tmp_path)
    events = []

    result = router.route(
        "Integrate Stripe Checkout webhook",
        mock=True,
        on_event=lambda e: events.append(e),
    )

    assert result.intent == "PREP_AND_EXECUTE"
    assert result.prep_invoked is True
    kinds = [e.kind for e in events]
    assert kinds == ["classified", "prep_start", "prep_complete", "execution_start", "execution_complete"]
    assert all(isinstance(e, RouterEvent) for e in events)

    classified = events[0]
    assert isinstance(classified.data["classification"], ClassificationResult)
    assert classified.data["engine"] == result.engine

    prep_complete = events[2]
    assert prep_complete.data["markdown"] == result.research_context
    assert prep_complete.data["source_url"] == result.research_source_url

    execution_complete = events[4]
    assert execution_complete.data["result"].exit_code == 0


def test_config_injection_routes_and_does_not_leak(tmp_path, monkeypatch):
    ambient_before = get_config()
    ambient_default_engine_before = ambient_before.default_engine

    captured = {}

    def fake_execute(self, payload, interactive=True, model_name=None, effort_level=5):
        captured["engine_name"] = self.name
        captured["model_name"] = model_name
        return ExecutionResult(
            status=EngineStatus.SUCCESS,
            engine_name=self.name,
            output_text="stubbed gemini output",
            exit_code=0,
            duration_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.0,
        )

    monkeypatch.setattr(GeminiExecutionEngine, "execute", fake_execute)

    router = _router(tmp_path, default_engine="gemini")
    # "fix typo in the readme" hits the classifier's fast-path regex, which resolves
    # its engine as `force_engine or config.default_engine` -- the one place
    # config.default_engine actually drives routing without an explicit override.
    result = router.route("fix typo in the readme", mock=False, interactive=False)

    assert result.engine == "gemini"
    assert captured["engine_name"] == "gemini"

    ambient_after = get_config()
    assert ambient_after is ambient_before
    assert ambient_after.default_engine == ambient_default_engine_before


def test_classify_does_not_execute(tmp_path, monkeypatch):
    router = _router(tmp_path)

    def fail_execute(*args, **kwargs):
        raise AssertionError("engine.execute() must not be called by classify()")

    monkeypatch.setattr("ai_router.engines.claude_engine.ClaudeCodeEngine.execute", fail_execute)
    monkeypatch.setattr("ai_router.engines.gemini_engine.GeminiExecutionEngine.execute", fail_execute)
    monkeypatch.setattr("ai_router.engines.codex_engine.CodexExecutionEngine.execute", fail_execute)

    classification = router.classify("Integrate Stripe Checkout webhook")

    assert isinstance(classification, ClassificationResult)
    assert classification.intent in {"EXECUTE_ONLY", "PREP_AND_EXECUTE", "RESEARCH_ONLY"}


def test_route_result_to_dict_is_json_serializable(tmp_path):
    router = _router(tmp_path)
    result = router.route("Build a login page", mock=True)

    payload = result.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["exit_code"] == 0
    assert round_tripped["engine"] == result.engine


def test_route_real_claude_engine_with_stub_binary(tmp_path):
    stub_path = tmp_path / "fake_claude"
    stub_path.write_text("#!/bin/sh\necho 'stub claude engine output'\nexit 0\n")
    os.chmod(stub_path, stub_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    router = _router(tmp_path, claude_binary_path=str(stub_path))

    result = router.route(
        "Add a docstring to the main function",
        engine="claude",
        mock=False,
        interactive=False,
    )

    assert result.engine == "claude"
    assert result.exit_code == 0
    assert "stub claude engine output" in result.output_text
