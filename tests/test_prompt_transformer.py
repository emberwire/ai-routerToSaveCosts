import pytest
from ai_router.prompt_transformer import CanonicalPromptAST, PromptTransformer


def test_prompt_transformation_claude():
    ast = CanonicalPromptAST(
        user_prompt="Build webhook handler",
        intent="PREP_AND_EXECUTE",
        complexity_score=4,
        injected_context="<untrusted_external_research_context>Stripe doc</untrusted_external_research_context>",
    )
    payload = PromptTransformer.transform(ast, "claude")
    assert payload.engine == "claude"
    assert "<task>" in payload.formatted_prompt
    assert "<untrusted_external_research_context>" in payload.formatted_prompt
    assert payload.budget_params.complexity_score == 4


def test_prompt_transformation_codex():
    ast = CanonicalPromptAST(
        user_prompt="Optimize Dijkstra algorithm",
        intent="EXECUTE_ONLY",
        complexity_score=5,
    )
    payload = PromptTransformer.transform(ast, "codex")
    assert payload.engine == "codex"
    assert payload.api_parameters.get("reasoning_effort") == "high"
    assert "User Objective" in payload.formatted_prompt


def test_prompt_transformation_gemini():
    ast = CanonicalPromptAST(
        user_prompt="Explain system architecture",
        intent="RESEARCH_ONLY",
        complexity_score=2,
    )
    payload = PromptTransformer.transform(ast, "gemini")
    assert payload.engine == "gemini"
    assert "Coding Task" in payload.formatted_prompt
