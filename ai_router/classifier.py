import re
import json
import time
from typing import Tuple, Optional
from dataclasses import dataclass
import httpx
from ai_router.config import get_config
from ai_router.context_scanner import ContextScanner


@dataclass
class ClassificationResult:
    intent: str               # "EXECUTE_ONLY", "PREP_AND_EXECUTE", "RESEARCH_ONLY"
    complexity_score: int     # 1 to 5
    suggested_engine: str     # "claude", "gemini", "codex"
    suggested_model: str      # e.g. "claude-3-opus", "claude-3-7-sonnet", "gemini-3.7-flash", "o3-mini"
    effort_level: int         # 1 to 5 (5 = extra / max reasoning)
    confidence: float
    reasoning: str
    is_fast_path: bool
    evaluation_duration_ms: float


class IntentClassifier:
    """
    Traffic Cop / Intent & Model Classifier:
    1. Fast-Path Regex Heuristic (<5ms) for obvious local commands.
    2. Gemini 3.7 Flash API (temperature: 0.0, thinking_budget: 0) for context-aware model & effort identification.
    3. Defaults to Claude Opus with Effort 5 (Extra) for heavy/standard Claude Code tasks.
    4. Fallback Heuristic if offline or API key missing.
    """

    FAST_EXECUTE_PATTERNS = [
        r"(?i)^(fix|correct)\s+(typo|spelling|syntax|indentation|lint)",
        r"(?i)^run\s+(pytest|tests?|npm\s+test|cargo\s+test|build)",
        r"(?i)^git\s+(status|diff|add|commit|push|checkout|branch)",
        r"(?i)^format\s+(this|code|file)",
        r"(?i)^rename\s+(variable|function|file)\s+",
        r"(?i)^add\s+a\s+comment\s+",
        r"(?i)^remove\s+(unused|dead)\s+",
    ]

    PREP_KEYWORDS = [
        "stripe", "supabase", "firebase", "oauth", "aws", "gcp", "azure", "docker",
        "kubernetes", "graphql", "rest api", "webhook", "sdk", "library", "documentation",
        "integrate", "migration", "install", "upgrade", "how to use", "api spec"
    ]

    @classmethod
    def evaluate(cls, user_prompt: str, repo_context: Optional[str] = None, force_engine: Optional[str] = None) -> ClassificationResult:
        start_time = time.time()
        config = get_config()

        # 1. Check Fast-Path (<5ms)
        for pattern in cls.FAST_EXECUTE_PATTERNS:
            if re.search(pattern, user_prompt.strip()):
                elapsed = (time.time() - start_time) * 1000
                engine = force_engine or config.default_engine
                model = "claude-3-5-haiku" if engine == "claude" else ("gemini-3.7-flash" if engine == "gemini" else "gpt-4o-mini")
                return ClassificationResult(
                    intent="EXECUTE_ONLY",
                    complexity_score=1,
                    suggested_engine=engine,
                    suggested_model=model,
                    effort_level=1,
                    confidence=0.99,
                    reasoning="Matched fast-path local edit pattern",
                    is_fast_path=True,
                    evaluation_duration_ms=elapsed,
                )

        # 2. Try Gemini 3.7 Flash API if configured and not offline
        if config.gemini_api_key and not config.offline_mode:
            try:
                result = cls._call_gemini_classifier(user_prompt, repo_context, force_engine)
                if result:
                    return result
            except Exception:
                pass

        # 3. Fallback Heuristic Classifier (Zero-Dep offline evaluation)
        return cls._fallback_heuristic_evaluate(user_prompt, repo_context, force_engine, start_time)

    @classmethod
    def _call_gemini_classifier(cls, user_prompt: str, repo_context: Optional[str], force_engine: Optional[str]) -> Optional[ClassificationResult]:
        config = get_config()
        start_time = time.time()

        system_instruction = (
            "You are an expert AI Model & Task Classifier for a developer CLI orchestrator. "
            "Analyze the prompt and codebase context, and select the optimal intent, engine, specific model, and reasoning effort.\n"
            "Default rule for Claude Code: default to Claude Opus with effort=5 (extra exhaustive reasoning) for serious engineering tasks, "
            "or pick Haiku/Sonnet if a lighter model is better suited.\n\n"
            "Output a strict JSON object with fields:\n"
            "- intent: 'EXECUTE_ONLY' (local edits, tests, refactoring), 'PREP_AND_EXECUTE' (external docs/APIs needed), 'RESEARCH_ONLY' (pure info).\n"
            "- complexity_score: integer 1 to 5.\n"
            "- suggested_engine: 'claude', 'gemini', or 'codex'.\n"
            "- suggested_model: specific model name (e.g. 'claude-3-opus', 'claude-3-7-sonnet', 'claude-3-5-haiku', 'gemini-3.7-flash', 'o3-mini', 'o1').\n"
            "- effort_level: integer 1 to 5 (default 5 for Claude Opus extra effort).\n"
            "- reasoning: 1-sentence explanation of why this model and effort level was chosen for this context.\n"
            "Output JSON ONLY."
        )

        user_content = f"Task Prompt: {user_prompt}\n"
        if repo_context:
            user_content += f"Codebase Context:\n{repo_context}\n"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent?key={config.gemini_api_key}"

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            }
        }

        with httpx.Client(timeout=2.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)

                elapsed = (time.time() - start_time) * 1000
                engine = force_engine or parsed.get("suggested_engine", config.default_engine)
                default_claude_model = config.claude_model
                model = parsed.get("suggested_model", default_claude_model if engine == "claude" else "gemini-3.7-flash")
                effort = int(parsed.get("effort_level", config.claude_default_effort if engine == "claude" else 3))

                return ClassificationResult(
                    intent=parsed.get("intent", "EXECUTE_ONLY"),
                    complexity_score=int(parsed.get("complexity_score", 3)),
                    suggested_engine=engine,
                    suggested_model=model,
                    effort_level=effort,
                    confidence=0.95,
                    reasoning=parsed.get("reasoning", "Gemini 3.7 Flash context-aware classification"),
                    is_fast_path=False,
                    evaluation_duration_ms=elapsed,
                )

        return None

    @classmethod
    def _fallback_heuristic_evaluate(cls, user_prompt: str, repo_context: Optional[str], force_engine: Optional[str], start_time: float) -> ClassificationResult:
        config = get_config()
        lower = user_prompt.lower()

        if lower.startswith("how does") or lower.startswith("what is") or lower.startswith("explain") or lower.startswith("info "):
            intent = "RESEARCH_ONLY"
            score = 2
        elif any(k in lower for k in cls.PREP_KEYWORDS):
            intent = "PREP_AND_EXECUTE"
            score = 4
        else:
            intent = "EXECUTE_ONLY"
            score = 3

        # Suggested engine & model
        if "algorithm" in lower or "optimize math" in lower or "dynamic programming" in lower:
            suggested_engine = "codex"
            suggested_model = "o3-mini"
            effort = 4
        elif "analyze all" in lower or "document whole repo" in lower or "entire codebase" in lower:
            suggested_engine = "gemini"
            suggested_model = "gemini-3.7-flash"
            effort = 3
        else:
            suggested_engine = "claude"
            # Default to Opus with Effort 5 Extra for Claude tasks
            suggested_model = config.claude_model # "claude-3-opus"
            effort = config.claude_default_effort # 5 (Extra)

        if force_engine:
            suggested_engine = force_engine
            if force_engine == "claude":
                suggested_model = config.claude_model
                effort = config.claude_default_effort

        elapsed = (time.time() - start_time) * 1000
        return ClassificationResult(
            intent=intent,
            complexity_score=score,
            suggested_engine=suggested_engine,
            suggested_model=suggested_model,
            effort_level=effort,
            confidence=0.90,
            reasoning=f"Identified optimal model {suggested_model} with effort {effort} based on task requirements",
            is_fast_path=False,
            evaluation_duration_ms=elapsed,
        )
