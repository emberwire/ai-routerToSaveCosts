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


def test_quality_gate_blocks_fast_path_on_scope_that_pattern_alone_would_miss():
    # SPEC-ai-engineering.md A13: this used to match the same fast-path
    # pattern as "Fix typo in auth.py" and dispatch to the cheapest model
    # at effort 1, because the regex reads only the opening words.
    res = IntentClassifier.evaluate("Fix syntax across the entire auth module")
    assert res.is_fast_path is False
    assert res.effort_level == 5


def test_quality_gate_escalates_a_destructive_git_command():
    res = IntentClassifier.evaluate("git commit the migration that drops the users table")
    assert res.is_fast_path is False
    assert res.effort_level == 5


def test_mutating_git_verbs_no_longer_fast_path():
    # commit/push/checkout/branch all mutate state; only read-only git verbs
    # (status/diff/log/show) may skip classification.
    res = IntentClassifier.evaluate("git commit -m done")
    assert res.is_fast_path is False
