from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class EngineStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    FALLBACK = "fallback"
    INTERRUPTED = "interrupted"


@dataclass
class ExecutionResult:
    status: EngineStatus
    engine_name: str
    output_text: str
    exit_code: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    error_message: Optional[str] = None
    gateway_metadata: Optional[Dict[str, Any]] = None


class BaseExecutionEngine(ABC):
    """
    Abstract Base Execution Engine.
    All models (Claude Code, Gemini, Codex/OpenAI) implement this interface.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def execute(
        self,
        prompt: str,
        context: Optional[str] = None,
        interactive: bool = True,
        complexity_score: int = 3,
        system_instruction: Optional[str] = None,
        model_name: Optional[str] = None,
        effort_level: int = 5,
    ) -> ExecutionResult:
        """Executes the prompt with context and returns structured result/telemetry."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if binary or API key is present for this engine."""
        pass
