import pytest
from ai_router.context_pruner import ContextPruner


def test_jaccard_similarity():
    text_a = "Stripe webhook checkout session completed"
    text_b = "Stripe webhook payment intent succeeded"
    sim = ContextPruner.compute_jaccard_similarity(text_a, text_b)
    assert 0.0 < sim < 1.0


def test_context_pruning_and_budgeting():
    raw_doc = (
        "Paragraph 1 with explanations.\n\n"
        "Paragraph 2 with more details.\n\n"
        "```typescript\nconst stripe = new Stripe();\n```\n\n"
        "Paragraph 4 long trailing text."
    )
    pruned, tokens = ContextPruner.prune_and_budget(raw_doc, max_tokens=20)
    assert len(pruned) > 0
    assert tokens <= 30
