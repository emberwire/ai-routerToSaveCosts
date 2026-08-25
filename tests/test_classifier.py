import pytest
from ai_router.classifier import IntentClassifier


def test_fast_path_classification():
    res = IntentClassifier.evaluate("Fix typo in auth.py")
    assert res.is_fast_path is True
    assert res.intent == "EXECUTE_ONLY"
    assert res.complexity_score == 1
    assert res.evaluation_duration_ms < 50.0


def test_heuristic_prep_classification():
    res = IntentClassifier.evaluate("Integrate Stripe checkout webhooks with database sync")
    assert res.intent == "PREP_AND_EXECUTE"
    assert res.complexity_score >= 3


def test_heuristic_research_classification():
    res = IntentClassifier.evaluate("Explain difference between REST and GraphQL")
    assert res.intent == "RESEARCH_ONLY"
