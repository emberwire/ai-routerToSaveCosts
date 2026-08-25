"""
AI-Routed CLI Agent (v4.0)
High-performance, secure LLM prompt router and execution orchestrator.
"""
from ai_router.api import AIRouter, RouteResult, RouterEvent
from ai_router.classifier import ClassificationResult
from ai_router.config import AppConfig
from ai_router.engines.base import ExecutionResult

__version__ = "4.0.0"

__all__ = [
    "AIRouter",
    "RouteResult",
    "RouterEvent",
    "AppConfig",
    "ClassificationResult",
    "ExecutionResult",
    "__version__",
]
