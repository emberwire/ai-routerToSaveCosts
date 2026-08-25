import pytest
from ai_router.engines.registry import get_engine_registry
from ai_router.engines.claude_engine import ClaudeCodeEngine
from ai_router.engines.gemini_engine import GeminiExecutionEngine
from ai_router.engines.codex_engine import CodexExecutionEngine


def test_engine_registry_resolution():
    registry = get_engine_registry()
    claude = registry.get_engine("claude")
    gemini = registry.get_engine("gemini")
    codex = registry.get_engine("codex")

    assert isinstance(claude, ClaudeCodeEngine)
    assert isinstance(gemini, GeminiExecutionEngine)
    assert isinstance(codex, CodexExecutionEngine)


def test_claude_binary_detection():
    engine = ClaudeCodeEngine()
    bin_path = engine.get_binary_path()
    assert bin_path is not None
    assert "claude" in bin_path
