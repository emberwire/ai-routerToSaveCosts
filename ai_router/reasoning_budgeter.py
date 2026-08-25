from enum import Enum
from dataclasses import dataclass
from typing import Literal


class ReasoningTier(str, Enum):
    NONE = "none"         # Zero budget (instant, e.g. classifier, simple formatting)
    LOW = "low"           # Low effort (e.g. syntax, typo, 1-line edits, doc reading)
    MEDIUM = "medium"     # Medium effort (e.g. single-file refactor, unit test generation)
    HIGH = "high"         # High effort (e.g. multi-file integration, Stripe flow, concurrency)
    MAX = "max"           # Max effort (e.g. deep mathematical algorithms, complex architecture)


@dataclass
class EngineBudgetParameters:
    engine: str
    complexity_score: int  # 1 to 5
    reasoning_tier: ReasoningTier
    openai_reasoning_effort: Literal["low", "medium", "high"]
    gemini_thinking_budget: int
    claude_effort_description: str


class ReasoningBudgeter:
    """
    Dynamic Reasoning Effort Budgeter.
    Maps task complexity scores (1-5) to engine-specific reasoning tokens and effort tiers.
    """

    @classmethod
    def get_budget(cls, engine: str, complexity_score: int = 3) -> EngineBudgetParameters:
        score = max(1, min(5, complexity_score))

        if score <= 1:
            tier = ReasoningTier.LOW
            openai_effort = "low"
            gemini_budget = 0
            claude_desc = "Fast execution without extended thinking"
        elif score == 2:
            tier = ReasoningTier.LOW
            openai_effort = "low"
            gemini_budget = 1024
            claude_desc = "Standard reasoning effort"
        elif score == 3:
            tier = ReasoningTier.MEDIUM
            openai_effort = "medium"
            gemini_budget = 4096
            claude_desc = "Balanced reasoning effort"
        elif score == 4:
            tier = ReasoningTier.HIGH
            openai_effort = "high"
            gemini_budget = 8192
            claude_desc = "High reasoning effort with step-by-step verification"
        else: # score == 5
            tier = ReasoningTier.MAX
            openai_effort = "high"
            gemini_budget = 16384
            claude_desc = "Maximum reasoning effort with exhaustive problem solving"

        return EngineBudgetParameters(
            engine=engine,
            complexity_score=score,
            reasoning_tier=tier,
            openai_reasoning_effort=openai_effort,
            gemini_thinking_budget=gemini_budget,
            claude_effort_description=claude_desc,
        )
