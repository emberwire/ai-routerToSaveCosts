from typing import Dict, Optional, List
from ai_router.engines.base import BaseExecutionEngine
from ai_router.engines.claude_engine import ClaudeCodeEngine
from ai_router.engines.gemini_engine import GeminiExecutionEngine
from ai_router.engines.codex_engine import CodexExecutionEngine
from ai_router.config import get_config


class EngineRegistry:
    """
    Pluggable Engine Registry and Resolver:
    Resolves requested engine or auto-routes based on task classification.
    """

    def __init__(self):
        self._engines: Dict[str, BaseExecutionEngine] = {
            "claude": ClaudeCodeEngine(),
            "gemini": GeminiExecutionEngine(),
            "codex": CodexExecutionEngine(),
            "openai": CodexExecutionEngine(),
        }

    def get_engine(self, engine_name: Optional[str] = None) -> BaseExecutionEngine:
        config = get_config()
        name = (engine_name or config.default_engine).lower()

        if name == "auto":
            # Default auto fallback to claude
            return self._engines.get("claude", ClaudeCodeEngine())

        if name in self._engines:
            return self._engines[name]

        # Default fallback
        return self._engines["claude"]

    def list_engines(self) -> List[str]:
        return ["claude", "gemini", "codex", "auto"]

    def get_engine_statuses(self) -> Dict[str, bool]:
        return {
            "claude": self._engines["claude"].is_available(),
            "gemini": self._engines["gemini"].is_available(),
            "codex": self._engines["codex"].is_available(),
        }


_global_registry: Optional[EngineRegistry] = None


def get_engine_registry() -> EngineRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = EngineRegistry()
    return _global_registry
