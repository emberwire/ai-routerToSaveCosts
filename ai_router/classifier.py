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
    confidence: float
    reasoning: str
    is_fast_path: bool
    evaluation_duration_ms: float


class IntentClassifier:
    """
    Traffic Cop / Intent Classifier:
    1. Fast-Path Regex Heuristic (<5ms) for obvious local commands and minor edits.
    2. Gemini 2.5 Flash API (temperature: 0.0, thinking_budget: 0) for sub-second 3-way routing.
    3. Fallback Heuristic if offline or API key missing.
    """

    # Fast-path regex triggers for instant EXECUTE_ONLY
    FAST_EXECUTE_PATTERNS = [
        r"(?i)^(fix|correct)\s+(typo|spelling|syntax|indentation|lint)",
        r"(?i)^run\s+(pytest|tests?|npm\s+test|cargo\s+test|build)",
        r"(?i)^git\s+(status|diff|add|commit|push|checkout|branch)",
        r"(?i)^format\s+(this|code|file)",
        r"(?i)^rename\s+(variable|function|file)\s+",
        r"(?i)^add\s+a\s+comment\s+",
        r"(?i)^remove\s+(unused|dead)\s+",
    ]

    # Patterns strongly suggesting PREP_AND_EXECUTE
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
                return ClassificationResult(
                    intent="EXECUTE_ONLY",
                    complexity_score=1,
                    suggested_engine=force_engine or config.default_engine,
                    confidence=0.99,
                    reasoning="Matched fast-path local edit pattern",
                    is_fast_path=True,
                    evaluation_duration_ms=elapsed,
                )

        # 2. Try Gemini 2.5 Flash API if configured and not offline
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
            "You are an ultra-fast task classifier for a software engineering CLI agent. "
            "Analyze the prompt and codebase context, and output a strict JSON object with fields:\n"
            "- intent: 'EXECUTE_ONLY' (local edits, tests, refactoring existing files), "
            "'PREP_AND_EXECUTE' (requires reading external API docs, web research, new 3rd-party library/SDK integration), "
            "or 'RESEARCH_ONLY' (informational queries without code editing).\n"
            "- complexity_score: integer from 1 (trivial 1-liner) to 5 (complex architecture / distributed algorithm).\n"
            "- suggested_engine: 'claude' (default for terminal coding), 'gemini' (large context / analysis), or 'codex' (deep algorithms).\n"
            "- reasoning: short 1-sentence rationale.\n"
            "Output JSON ONLY."
        )

        user_content = f"Task Prompt: {user_prompt}\n"
        if repo_context:
            user_content += f"Codebase Context: {repo_context}\n"

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
                return ClassificationResult(
                    intent=parsed.get("intent", "EXECUTE_ONLY"),
                    complexity_score=int(parsed.get("complexity_score", 3)),
                    suggested_engine=force_engine or parsed.get("suggested_engine", config.default_engine),
                    confidence=0.95,
                    reasoning=parsed.get("reasoning", "Gemini 2.5 Flash classification"),
                    is_fast_path=False,
                    evaluation_duration_ms=elapsed,
                )

        return None

    @classmethod
    def _fallback_heuristic_evaluate(cls, user_prompt: str, repo_context: Optional[str], force_engine: Optional[str], start_time: float) -> ClassificationResult:
        config = get_config()
        lower = user_prompt.lower()

        # Pure research queries
        if lower.startswith("how does") or lower.startswith("what is") or lower.startswith("explain") or lower.startswith("info "):
            intent = "RESEARCH_ONLY"
            score = 2
        elif any(k in lower for k in cls.PREP_KEYWORDS):
            intent = "PREP_AND_EXECUTE"
            score = 3 if len(user_prompt.split()) < 15 else 4
        else:
            intent = "EXECUTE_ONLY"
            score = 2 if len(user_prompt.split()) < 10 else 3

        # Suggested engine
        if "algorithm" in lower or "optimize math" in lower or "dynamic programming" in lower:
            suggested = "codex"
        elif "analyze all" in lower or "document whole repo" in lower or "entire codebase" in lower:
            suggested = "gemini"
        else:
            suggested = "claude"

        elapsed = (time.time() - start_time) * 1000
        return ClassificationResult(
            intent=intent,
            complexity_score=score,
            suggested_engine=force_engine or suggested,
            confidence=0.85,
            reasoning="Heuristic keyword analysis",
            is_fast_path=False,
            evaluation_duration_ms=elapsed,
        )
