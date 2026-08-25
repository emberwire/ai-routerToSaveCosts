import pytest
from ai_router.quality_gate import QualityGate


# Verified live 2026-08-25 (SPEC-ai-engineering.md A13): every one of these
# used to fast-path to claude-haiku-4-5 at effort 1 on a bare regex match
# of the opening words, discarding everything named after them.
DANGEROUS_PROMPTS = [
    "Fix syntax across the entire auth module",
    "Fix lint in the payment reconciliation service",
    "correct spelling in the PPM offering document",
    "remove unused code from the crypto signing path",
    "git commit the migration that drops the users table",
    "rename function verifyWebhookSignature everywhere",
]

# Must keep fast-pathing. In particular "Fix typo in auth.py" is the
# existing regression test in test_classifier.py - a sensitive-domain word
# alone (auth) must not disqualify a genuinely trivial single-file edit;
# it only escalates when paired with a scope noun (module/service/path/...).
SAFE_PROMPTS = [
    "Fix typo in README.md",
    "Fix typo in auth.py",
    "run pytest",
    "git status",
    "git diff",
    "remove unused imports in utils.py",
    # Verified 2026-08-25: the destructive-verb regex's first draft matched
    # \w* after the verb stem and caught "dropdown" as a hit on "drop".
    "Fix lint in dropdown.py",
]

# Found missing 2026-08-25 by adversarial verification of the first draft:
# these are synonyms/inflections of signals already in the word lists and
# reproduced the A13 failure mode verbatim - "fix typo system-wide" fast-
# pathed to Haiku at effort 1 exactly like the original bug report's
# "across the entire auth module" was supposed to have been fixed.
ADVERSARIAL_DANGEROUS_PROMPTS = [
    "fix typo system-wide",
    "fix spelling globally",
    "fix typos repo-wide",
    "correct indentation org-wide",
    "fix typo in each file",
    "wipe the cache",
    "erase the migration history",
    "nuke the staging environment",
    "clean out the billing pipeline",
]


@pytest.mark.parametrize("prompt", DANGEROUS_PROMPTS + ADVERSARIAL_DANGEROUS_PROMPTS)
def test_sensitivity_override_trips_on_dangerous_prompts(prompt):
    floor = QualityGate.sensitivity_override(prompt)
    assert floor is not None, f"expected an override for: {prompt!r}"
    assert floor.min_effort == 5
    assert floor.require_heavy_model is True


@pytest.mark.parametrize("prompt", SAFE_PROMPTS)
def test_sensitivity_override_does_not_trip_on_safe_prompts(prompt):
    assert QualityGate.sensitivity_override(prompt) is None


@pytest.mark.parametrize("prompt", DANGEROUS_PROMPTS + ADVERSARIAL_DANGEROUS_PROMPTS)
def test_dangerous_prompts_are_not_fast_path_eligible(prompt):
    assert QualityGate.fast_path_eligible(prompt) is False


@pytest.mark.parametrize("prompt", SAFE_PROMPTS)
def test_safe_prompts_stay_fast_path_eligible(prompt):
    assert QualityGate.fast_path_eligible(prompt) is True


def test_length_bound_disqualifies_a_long_prompt_even_with_no_other_signal():
    long_prompt = "fix typo in the readme file that we updated last week during the sprint planning session"
    assert len(long_prompt.split()) > QualityGate.MAX_FAST_PATH_WORDS
    assert QualityGate.fast_path_eligible(long_prompt) is False


def test_apply_never_lowers_an_existing_effort_level():
    # A classifier that already returned effort 5 for a trivial intent must
    # not be clamped down to the intent floor.
    from ai_router.config import get_config
    effort, model, reason = QualityGate.apply(
        "run pytest", "EXECUTE_ONLY", 5, "claude-opus-5", "claude", get_config()
    )
    assert effort == 5
    assert model == "claude-opus-5"
    assert reason is None


def test_apply_raises_effort_and_swaps_to_heavy_model_when_floor_requires_it():
    from ai_router.config import get_config
    config = get_config()
    effort, model, reason = QualityGate.apply(
        "analyze all files in src/", "EXECUTE_ONLY", 3, config.gemini_model, "gemini", config
    )
    assert effort == 5
    assert model == config.gemini_exec_model
    assert reason is not None


def test_destructive_regex_does_not_false_positive_on_dropdown():
    # First draft used \w* after the verb stem and matched "dropdown" as a
    # hit on "drop". Inflections are enumerated explicitly now.
    assert QualityGate.sensitivity_override("Fix lint in dropdown.py") is None


def test_mock_classification_is_gated_the_same_as_the_real_classifier():
    # Mock mode has its own keyword logic and never calls IntentClassifier,
    # so fixing the real path alone would leave --mock demonstrating the
    # pre-fix behavior. Found 2026-08-25 by adversarial verification.
    from ai_router.mock_services import MockServices

    trivial = MockServices.mock_classification("Fix typo in README.md")
    assert trivial.is_fast_path is True
    assert trivial.effort_level == 1

    dangerous = MockServices.mock_classification("fix typo system-wide")
    assert dangerous.is_fast_path is False
    assert dangerous.effort_level == 5
