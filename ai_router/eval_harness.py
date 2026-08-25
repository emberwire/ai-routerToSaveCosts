import time
from typing import List, Dict, Any
from dataclasses import dataclass
from ai_router.classifier import IntentClassifier


@dataclass
class EvalTestCase:
    prompt: str
    expected_intent: str
    expected_min_complexity: int
    category: str


@dataclass
class EvalReport:
    total_cases: int
    correct_intents: int
    accuracy_percentage: float
    avg_latency_ms: float
    results: List[Dict[str, Any]]


class EvalHarness:
    """
    AI Routing Accuracy & Benchmark Harness (`ai eval`).
    Evaluates classifier performance and latency across representative software engineering prompts.
    """

    BENCHMARK_CASES = [
        EvalTestCase("Fix typo in variable name", "EXECUTE_ONLY", 1, "Fast Path / Typo"),
        EvalTestCase("Run pytest across unit tests", "EXECUTE_ONLY", 1, "Terminal Command"),
        EvalTestCase("Refactor database schema to add soft delete column", "EXECUTE_ONLY", 2, "Local Refactor"),
        EvalTestCase("Integrate Stripe checkout session webhook with HMAC signature verification", "PREP_AND_EXECUTE", 3, "External API"),
        EvalTestCase("How to implement Supabase auth with Next.js 14 server actions", "PREP_AND_EXECUTE", 3, "Framework / SDK"),
        EvalTestCase("Explain the difference between optimistic and pessimistic locking", "RESEARCH_ONLY", 2, "Informational"),
        EvalTestCase("Deploy docker container to AWS ECS Fargate", "PREP_AND_EXECUTE", 3, "Cloud Infrastructure"),
        EvalTestCase("Optimize dynamic programming traveling salesman algorithm", "EXECUTE_ONLY", 4, "Algorithms"),
    ]

    @classmethod
    def run_eval(cls) -> EvalReport:
        correct = 0
        total_lat = 0.0
        results = []

        for case in cls.BENCHMARK_CASES:
            res = IntentClassifier.evaluate(case.prompt)
            total_lat += res.evaluation_duration_ms

            is_correct = (res.intent == case.expected_intent)
            if is_correct:
                correct += 1

            results.append({
                "prompt": case.prompt,
                "category": case.category,
                "expected": case.expected_intent,
                "actual": res.intent,
                "complexity": res.complexity_score,
                "latency_ms": res.evaluation_duration_ms,
                "fast_path": res.is_fast_path,
                "pass": is_correct,
            })

        acc = (correct / len(cls.BENCHMARK_CASES)) * 100
        avg_lat = total_lat / len(cls.BENCHMARK_CASES)

        return EvalReport(
            total_cases=len(cls.BENCHMARK_CASES),
            correct_intents=correct,
            accuracy_percentage=acc,
            avg_latency_ms=avg_lat,
            results=results,
        )
