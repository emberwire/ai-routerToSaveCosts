import pytest
from ai_router.mock_services import MockServices
from ai_router.prompt_transformer import CanonicalPromptAST, PromptTransformer
from ai_router.engines.registry import get_engine_registry


def test_end_to_end_mock_pipeline_claude():
    prompt = "Integrate Stripe Checkout webhook"
    classification = MockServices.mock_classification(prompt)
    assert classification.intent == "PREP_AND_EXECUTE"

    prep = MockServices.mock_n8n_prep(prompt)
    assert prep.success is True
    assert prep.sanitized_context is not None

    ast = CanonicalPromptAST(
        user_prompt=prompt,
        intent=classification.intent,
        complexity_score=classification.complexity_score,
        injected_context=prep.sanitized_context.quarantined_markdown,
    )
    payload = PromptTransformer.transform(ast, "claude")
    assert "<untrusted_external_research_context" in payload.formatted_prompt

    exec_res = MockServices.mock_execution("claude", prompt, prep.sanitized_context.quarantined_markdown)
    assert exec_res.exit_code == 0
    assert exec_res.status.value == "success"
