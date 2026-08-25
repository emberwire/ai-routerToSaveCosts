import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ai_router.audit_logger import AuditLogger
from ai_router.circuit_breaker import get_circuit_breaker
from ai_router.classifier import ClassificationResult, IntentClassifier
from ai_router.config import AppConfig, config_scope
from ai_router.context_scanner import ContextScanner
from ai_router.diagnostics import Diagnostics, DiagnosticCheck
from ai_router.engines.registry import get_engine_registry
from ai_router.mock_services import MockServices
from ai_router.n8n_pipeline import N8nResearchPipeline
from ai_router.prompt_transformer import CanonicalPromptAST, PromptTransformer
from ai_router.security_guard import SecurityGuard
from ai_router.telemetry_roi import TelemetryROI


@dataclass
class RouteResult:
    """
    Structured, Rich-free result of a single `AIRouter.route()` call.
    Everything a host application needs to render, log, or forward the outcome
    of a routed prompt without depending on any CLI/console object.
    """
    prompt: str
    sanitized_prompt: str
    intent: str
    complexity_score: int
    engine: str
    model: str
    effort: int
    confidence: float
    reasoning: str
    is_fast_path: bool
    dlp_violations: List[str]
    prep_invoked: bool
    research_context: Optional[str]
    research_source_url: Optional[str]
    circuit_state: str
    executed: bool
    output_text: str
    exit_code: int
    status: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float
    error_message: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Plain JSON-serializable representation (no Rich or dataclass objects)."""
        return asdict(self)


@dataclass
class RouterEvent:
    """
    A single progress notification emitted by `AIRouter.route()` via `on_event`.
    `data` carries whatever the CLI (or another consumer) needs to render this
    step; it may hold non-JSON-serializable objects (e.g. `ClassificationResult`)
    since it never crosses a process/network boundary.
    """
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)


class AIRouter:
    """
    Public, in-process facade over the AI-Routed CLI pipeline.

    Unlike `ai_router.cli.run_pipeline`, `AIRouter` never touches stdout/stderr,
    always returns structured data (`RouteResult`), and accepts an injectable
    `AppConfig` scoped to the duration of each call rather than reading only from
    ambient CWD/env globals. This keeps the door open for a future async web
    service or MCP tool to wrap the same orchestration logic.
    """

    def __init__(self, config: Optional[AppConfig] = None, **overrides: Any):
        self.config: AppConfig = config if config is not None else AppConfig.load_hierarchical()
        for key, value in overrides.items():
            setattr(self.config, key, value)

    def route(
        self,
        prompt: str,
        *,
        engine: Optional[str] = None,
        prep: Optional[bool] = None,
        interactive: bool = False,
        mock: bool = False,
        offline: bool = False,
        workspace: Optional[str] = None,
        on_event: Optional[Callable[[RouterEvent], None]] = None,
    ) -> RouteResult:
        """
        Runs the full classify -> (optional prep) -> transform -> dispatch pipeline
        in-process and returns a `RouteResult`. Never prints. `interactive` defaults
        to False so a library caller never has the TTY handed over unless explicitly
        requested; the CLI opts back into `interactive=True`.

        `prep`: None decides from classification (current CLI default behavior),
        True forces the research prep pipeline, False bypasses it.
        """

        def emit(kind: str, **data: Any) -> None:
            if on_event is not None:
                on_event(RouterEvent(kind=kind, data=data))

        with config_scope(self.config):
            config = self.config
            if offline:
                config.offline_mode = True

            start_time = time.time()

            # Step 1: CSO Local Data Loss Prevention (DLP) Scan
            dlp_violations: List[str] = []
            sanitized_prompt = prompt
            if config.enable_dlp_scanner:
                dlp_res = SecurityGuard.scan_dlp(prompt, redact=True)
                if not dlp_res.is_clean:
                    dlp_violations = dlp_res.violations
                    sanitized_prompt = dlp_res.sanitized_text
                    emit("dlp_violation", violations=dlp_violations)

            # Step 2: Local Repo Micro-Fingerprint Scan (<10ms)
            repo_summary = ContextScanner.get_summary_prompt_context(root_path=workspace)

            # Step 3: Intent & Complexity & Model Classification
            if mock:
                classification = MockServices.mock_classification(sanitized_prompt, force_engine=engine)
            else:
                classification = IntentClassifier.evaluate(sanitized_prompt, repo_context=repo_summary, force_engine=engine)

            # Resolve target engine & model
            target_engine_name = engine or classification.suggested_engine or config.default_engine
            if target_engine_name == "auto":
                target_engine_name = classification.suggested_engine or "claude"

            emit("classified", classification=classification, engine=target_engine_name)

            # Determine whether to run prep pipeline
            force_prep = prep is True
            bypass_prep = prep is False
            should_prep = (classification.intent == "PREP_AND_EXECUTE" or force_prep) and not bypass_prep

            prep_context_md: Optional[str] = None
            source_url: Optional[str] = None
            raw_len = 0
            pruned_tokens = 0
            circuit_tripped = False

            # Step 4: Research Pipeline (if required)
            if should_prep:
                emit("prep_start")
                if mock:
                    prep_result = MockServices.mock_n8n_prep(sanitized_prompt)
                else:
                    prep_result = N8nResearchPipeline.execute_prep(sanitized_prompt, repo_context=repo_summary)

                if prep_result.success and prep_result.sanitized_context:
                    prep_context_md = prep_result.sanitized_context.quarantined_markdown
                    source_url = prep_result.source_url
                    raw_len = len(prep_result.sanitized_context.raw_text)
                    pruned_tokens = max(10, len(prep_context_md.split()))
                    emit("prep_complete", markdown=prep_context_md, source_url=source_url)
                else:
                    circuit_tripped = prep_result.circuit_tripped
                    emit("prep_failed", error_message=prep_result.error_message)

            elif classification.intent == "RESEARCH_ONLY":
                # Pure information display: no code execution requested.
                emit("research_only")
                duration_ms = (time.time() - start_time) * 1000

                # Deliberate improvement over the CLI's run_pipeline: the CLI returns here
                # before recording audit/telemetry for RESEARCH_ONLY. This is a real routed
                # command, so the facade records both.
                AuditLogger.log_event(
                    user_prompt=prompt,
                    intent=classification.intent,
                    engine=target_engine_name,
                    prep_invoked=False,
                    prep_context=None,
                    dlp_violations=dlp_violations,
                    duration_ms=duration_ms,
                    circuit_status=get_circuit_breaker().state.value,
                    exit_code=0,
                    extra_metadata={"model": classification.suggested_model, "effort": classification.effort_level},
                )
                TelemetryROI.record_command(
                    intent=classification.intent,
                    prep_used=False,
                    raw_context_length=0,
                    pruned_context_tokens=0,
                    duration_ms=duration_ms,
                    is_cache_hit=False,
                    circuit_tripped=False,
                )

                return RouteResult(
                    prompt=prompt,
                    sanitized_prompt=sanitized_prompt,
                    intent=classification.intent,
                    complexity_score=classification.complexity_score,
                    engine=target_engine_name,
                    model=classification.suggested_model,
                    effort=classification.effort_level,
                    confidence=classification.confidence,
                    reasoning=classification.reasoning,
                    is_fast_path=classification.is_fast_path,
                    dlp_violations=dlp_violations,
                    prep_invoked=False,
                    research_context=None,
                    research_source_url=None,
                    circuit_state=get_circuit_breaker().state.value,
                    executed=False,
                    output_text="",
                    exit_code=0,
                    status="RESEARCH_ONLY",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    duration_ms=duration_ms,
                    error_message=None,
                )

            # Step 5: Canonical Prompt Transformation
            ast = CanonicalPromptAST(
                user_prompt=sanitized_prompt,
                intent=classification.intent,
                complexity_score=classification.complexity_score,
                injected_context=prep_context_md,
                source_url=source_url,
                repo_context=repo_summary,
            )
            payload = PromptTransformer.transform(ast, target_engine_name)

            # Step 6: Dispatch to Execution Engine
            registry = get_engine_registry()
            engine_instance = registry.get_engine(target_engine_name)

            emit(
                "execution_start",
                engine=target_engine_name,
                model=classification.suggested_model,
                effort=classification.effort_level,
                mock=mock,
            )

            if mock:
                exec_result = MockServices.mock_execution(
                    target_engine_name,
                    sanitized_prompt,
                    prep_context_md,
                    model=classification.suggested_model,
                    effort=classification.effort_level,
                )
            else:
                exec_result = engine_instance.execute(
                    payload=payload,
                    interactive=interactive,
                    model_name=classification.suggested_model,
                    effort_level=classification.effort_level,
                )

            emit(
                "execution_complete",
                result=exec_result,
                engine=target_engine_name,
                model=classification.suggested_model,
                effort=classification.effort_level,
                mock=mock,
            )

            duration_ms = (time.time() - start_time) * 1000

            # Step 7: Record Audit Log & Telemetry
            AuditLogger.log_event(
                user_prompt=prompt,
                intent=classification.intent,
                engine=target_engine_name,
                prep_invoked=should_prep,
                prep_context=prep_context_md,
                dlp_violations=dlp_violations,
                duration_ms=duration_ms,
                circuit_status=get_circuit_breaker().state.value,
                exit_code=exec_result.exit_code,
                extra_metadata={"model": classification.suggested_model, "effort": classification.effort_level},
            )

            TelemetryROI.record_command(
                intent=classification.intent,
                prep_used=should_prep,
                raw_context_length=raw_len,
                pruned_context_tokens=pruned_tokens,
                duration_ms=duration_ms,
                is_cache_hit=bool(exec_result.gateway_metadata and exec_result.gateway_metadata.get("cache_status") == "HIT"),
                circuit_tripped=circuit_tripped,
            )

            return RouteResult(
                prompt=prompt,
                sanitized_prompt=sanitized_prompt,
                intent=classification.intent,
                complexity_score=classification.complexity_score,
                engine=target_engine_name,
                model=classification.suggested_model,
                effort=classification.effort_level,
                confidence=classification.confidence,
                reasoning=classification.reasoning,
                is_fast_path=classification.is_fast_path,
                dlp_violations=dlp_violations,
                prep_invoked=should_prep,
                research_context=prep_context_md,
                research_source_url=source_url,
                circuit_state=get_circuit_breaker().state.value,
                executed=True,
                output_text=exec_result.output_text,
                exit_code=exec_result.exit_code,
                status=exec_result.status.value,
                input_tokens=exec_result.input_tokens,
                output_tokens=exec_result.output_tokens,
                cost_usd=exec_result.cost_usd,
                duration_ms=duration_ms,
                error_message=exec_result.error_message,
            )

    def classify(
        self,
        prompt: str,
        *,
        workspace: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> ClassificationResult:
        """
        Cheap classification only: DLP-sanitizes and classifies `prompt` without
        running the research prep pipeline or dispatching to an execution engine.
        Useful for a host app that wants to preview routing/cost before committing.
        """
        with config_scope(self.config):
            config = self.config
            sanitized_prompt = prompt
            if config.enable_dlp_scanner:
                dlp_res = SecurityGuard.scan_dlp(prompt, redact=True)
                if not dlp_res.is_clean:
                    sanitized_prompt = dlp_res.sanitized_text

            repo_summary = ContextScanner.get_summary_prompt_context(root_path=workspace)
            return IntentClassifier.evaluate(sanitized_prompt, repo_context=repo_summary, force_engine=engine)

    def health(self) -> List[DiagnosticCheck]:
        """Runs the same checks as `ai doctor`, scoped to this router's config."""
        with config_scope(self.config):
            return Diagnostics.run_all_checks()
