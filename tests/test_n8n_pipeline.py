import pytest
from ai_router.n8n_pipeline import N8nResearchPipeline
from ai_router.circuit_breaker import get_circuit_breaker


def test_n8n_pipeline_local_fallback_when_offline():
    # Calling with an unreachable port triggers local fallback
    res = N8nResearchPipeline.execute_prep("How to configure Docker compose")
    assert res.success is True
    assert res.sanitized_context is not None
    assert "<untrusted_external_research_context" in res.sanitized_context.quarantined_markdown
