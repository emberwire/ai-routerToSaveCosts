import time
import httpx
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from ai_router.config import get_config
from ai_router.engines.registry import get_engine_registry
from ai_router.circuit_breaker import get_circuit_breaker


@dataclass
class DiagnosticCheck:
    category: str
    name: str
    status: str  # "PASS", "WARN", "FAIL", "INFO"
    message: str
    latency_ms: Optional[float] = None


class Diagnostics:
    """
    CTO Diagnostics Engine (`ai doctor`).
    Performs 1-click self-healing health checks across all system layers.
    """

    @classmethod
    def run_all_checks(cls) -> List[DiagnosticCheck]:
        config = get_config()
        results = []

        # 1. Execution Engines Check
        registry = get_engine_registry()
        claude_engine = registry.get_engine("claude")
        claude_bin = claude_engine.get_binary_path()
        if claude_bin:
            results.append(DiagnosticCheck("Engines", "Claude Code CLI", "PASS", f"Detected at: {claude_bin}"))
        else:
            results.append(DiagnosticCheck("Engines", "Claude Code CLI", "WARN", "Not found in PATH or /opt/homebrew/bin/claude"))

        if config.gemini_api_key:
            results.append(DiagnosticCheck("Engines", "Gemini Engine Key", "PASS", "GEMINI_API_KEY is configured"))
        else:
            results.append(DiagnosticCheck("Engines", "Gemini Engine Key", "WARN", "GEMINI_API_KEY is empty (using heuristic classifier fallback)"))

        if config.openai_api_key:
            results.append(DiagnosticCheck("Engines", "OpenAI / Codex Key", "PASS", "OPENAI_API_KEY is configured"))
        else:
            results.append(DiagnosticCheck("Engines", "OpenAI / Codex Key", "WARN", "OPENAI_API_KEY is empty"))

        # 2. n8n Research Pipeline Check
        breaker = get_circuit_breaker()
        start = time.time()
        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(config.n8n_webhook_url)
                lat = (time.time() - start) * 1000
                results.append(DiagnosticCheck("Research", "n8n Webhook", "PASS", f"Reachable at {config.n8n_webhook_url}", latency_ms=lat))
        except Exception as e:
            results.append(DiagnosticCheck("Research", "n8n Webhook", "WARN", f"Unreachable ({str(e)[:40]}...). Circuit breaker fail-open active."))

        results.append(DiagnosticCheck("Resilience", "Circuit Breaker", "PASS", f"State: {breaker.state.value} (Failures: {breaker.failure_count})"))

        # 3. Cloudflare AI Gateway Check
        if config.enable_cf_gateway and config.cf_account_id and config.cf_gateway_id:
            results.append(DiagnosticCheck("Gateway", "Cloudflare AI Gateway", "PASS", f"Active (Account: {config.cf_account_id[:6]}..., Gateway: {config.cf_gateway_id})"))
        else:
            results.append(DiagnosticCheck("Gateway", "Cloudflare AI Gateway", "INFO", "Disabled / Direct Provider Routing"))

        # 4. Security & Audit Guardrails
        results.append(DiagnosticCheck("Security", "DLP Scanner", "PASS" if config.enable_dlp_scanner else "WARN", "Active" if config.enable_dlp_scanner else "Disabled"))
        results.append(DiagnosticCheck("Security", "Prompt Injection Quarantine", "PASS" if config.enable_prompt_injection_quarantine else "WARN", "Active" if config.enable_prompt_injection_quarantine else "Disabled"))
        results.append(DiagnosticCheck("Compliance", "Audit Trail (JSONL)", "PASS" if config.enable_audit_logging else "WARN", f"Logging to {config.get_audit_log_path()}"))

        return results
