import pytest
from ai_router.engines.registry import get_engine_registry
from ai_router.engines.claude_engine import ClaudeCodeEngine
from ai_router.engines.gemini_engine import GeminiExecutionEngine
from ai_router.engines.codex_engine import CodexExecutionEngine
from ai_router.prompt_transformer import CanonicalPromptAST, PromptTransformer
from ai_router.config import get_config


def test_engine_registry_resolution():
    registry = get_engine_registry()
    claude = registry.get_engine("claude")
    gemini = registry.get_engine("gemini")
    codex = registry.get_engine("codex")

    assert isinstance(claude, ClaudeCodeEngine)
    assert isinstance(gemini, GeminiExecutionEngine)
    assert isinstance(codex, CodexExecutionEngine)


def test_claude_binary_detection():
    engine = ClaudeCodeEngine()
    bin_path = engine.get_binary_path()
    assert bin_path is not None
    assert "claude" in bin_path


def _make_payload(engine: str, repo_context: str = "Codebase Tech Stack: Python"):
    ast = CanonicalPromptAST(
        user_prompt="Build a Stripe Checkout webhook",
        intent="PREP_AND_EXECUTE",
        complexity_score=4,
        injected_context='<untrusted_external_research_context source="https://docs.stripe.com">doc</untrusted_external_research_context>',
        repo_context=repo_context,
    )
    return PromptTransformer.transform(ast, engine)


def test_claude_engine_consumes_transformed_payload(monkeypatch):
    payload = _make_payload("claude")
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env", {})
        return FakeResult()

    monkeypatch.setattr("subprocess.run", fake_run)

    engine = ClaudeCodeEngine()
    result = engine.execute(payload=payload, interactive=False, model_name="claude-opus-5", effort_level=5)

    assert result.status.value == "success"
    args = captured["args"]
    assert args[0] == engine.get_binary_path()
    assert "-p" in args
    assert "--model" in args and args[args.index("--model") + 1] == "claude-opus-5"
    assert "--append-system-prompt" in args
    system_prompt = args[args.index("--append-system-prompt") + 1]
    assert "expert coding assistant" in system_prompt
    assert "effort_budget" in system_prompt
    # The transformed prompt (repo context + quarantined research + task), not raw prompt/context.
    sent_prompt = args[-1]
    assert "<repo_context>" in sent_prompt
    assert "<untrusted_external_research_context" in sent_prompt
    assert "<task>" in sent_prompt
    assert captured["env"]["ANTHROPIC_MODEL"] == "claude-opus-5"


def test_gemini_engine_consumes_transformed_payload(monkeypatch):
    config = get_config()
    monkeypatch.setattr(config, "gemini_api_key", "fake-key")

    payload = _make_payload("gemini")
    captured = {}

    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            return iter([])

    class FakeStreamCtx:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *exc):
            return False

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, json=None, headers=None):
            captured["json"] = json
            return FakeStreamCtx()

    monkeypatch.setattr("httpx.Client", lambda *a, **k: FakeClient())

    engine = GeminiExecutionEngine()
    result = engine.execute(payload=payload, interactive=False, model_name=None, effort_level=5)

    assert result.status.value == "success"
    body = captured["json"]
    text = body["contents"][0]["parts"][0]["text"]
    assert "Project Environment" in text
    assert "Pre-Fetched Reference Material" in text
    assert body["systemInstruction"]["parts"][0]["text"] == payload.system_instruction
    assert body["generationConfig"]["thinkingConfig"]["thinking_budget"] == payload.budget_params.gemini_thinking_budget


def test_codex_engine_consumes_transformed_payload(monkeypatch):
    config = get_config()
    monkeypatch.setattr(config, "openai_api_key", "fake-key")

    payload = _make_payload("codex")
    captured = {}

    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            return iter([])

    class FakeStreamCtx:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *exc):
            return False

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, json=None, headers=None):
            captured["json"] = json
            return FakeStreamCtx()

    monkeypatch.setattr("httpx.Client", lambda *a, **k: FakeClient())

    engine = CodexExecutionEngine()
    result = engine.execute(payload=payload, interactive=False, model_name=None, effort_level=5)

    assert result.status.value == "success"
    body = captured["json"]
    assert body["messages"][-1]["content"] == payload.formatted_prompt
    assert body["reasoning_effort"] == payload.api_parameters["reasoning_effort"]
