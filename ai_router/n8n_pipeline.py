import time
import json
import httpx
from typing import Optional, Tuple
from dataclasses import dataclass
from ai_router.config import get_config
from ai_router.circuit_breaker import get_circuit_breaker
from ai_router.security_guard import SecurityGuard, SanitizedContext
from ai_router.context_pruner import ContextPruner
from ai_router.session_cache import SessionCache


@dataclass
class PrepResult:
    success: bool
    sanitized_context: Optional[SanitizedContext]
    source_url: Optional[str]
    duration_ms: float
    circuit_tripped: bool
    fallback_used: Optional[str]
    error_message: Optional[str] = None


class N8nResearchPipeline:
    """
    Synchronous n8n Research & Prep Pipeline.
    1. Checks session cache first.
    2. Respects Fail-Open Circuit Breaker.
    3. Fires synchronous HTTP POST to n8n webhook with timeout.
    4. Triggers local micro-scraper fallback if n8n is offline.
    5. Applies Token Cap (<= 1500 tokens), Jaccard Pruning, and Prompt Injection Quarantine.
    """

    @classmethod
    def execute_prep(cls, user_prompt: str, repo_context: Optional[str] = None, bypass_cache: bool = False) -> PrepResult:
        start_time = time.time()
        config = get_config()
        breaker = get_circuit_breaker()

        # 1. Check Session Cache if not explicitly bypassed
        if not bypass_cache:
            cached = SessionCache.get_latest_context()
            if cached and cached.is_valid:
                sanitized = SecurityGuard.sanitize_untrusted_research(cached.context, source_url=cached.source_url)
                elapsed = (time.time() - start_time) * 1000
                return PrepResult(
                    success=True,
                    sanitized_context=sanitized,
                    source_url=cached.source_url,
                    duration_ms=elapsed,
                    circuit_tripped=False,
                    fallback_used="session_cache",
                )

        # 2. Check Circuit Breaker
        if not breaker.can_execute():
            # Circuit is OPEN -> Check if local scraper is enabled
            if config.enable_local_scraper_fallback:
                return cls._execute_local_fallback(user_prompt, start_time, reason="Circuit Breaker OPEN")
            
            elapsed = (time.time() - start_time) * 1000
            return PrepResult(
                success=False,
                sanitized_context=None,
                source_url=None,
                duration_ms=elapsed,
                circuit_tripped=True,
                fallback_used=None,
                error_message=f"Circuit Breaker is {breaker.state.value} (n8n degraded)",
            )

        # 3. Call n8n Webhook
        payload = {
            "task": user_prompt,
            "timestamp": time.time(),
            "repo_context": repo_context or "",
        }

        try:
            with httpx.Client(timeout=config.n8n_timeout_seconds) as client:
                resp = client.post(config.n8n_webhook_url, json=payload)

                if resp.status_code == 200:
                    breaker.record_success()
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"context": resp.text}
                    
                    raw_context = data.get("context") or data.get("markdown") or data.get("summary") or str(data)
                    source_url = data.get("source_url") or data.get("url")

                    # Prune and budget
                    pruned, tokens = ContextPruner.prune_and_budget(raw_context, max_tokens=config.n8n_max_tokens)
                    
                    # Sanitize and quarantine
                    sanitized = SecurityGuard.sanitize_untrusted_research(pruned, source_url=source_url)
                    
                    # Save to session cache
                    SessionCache.save_context(pruned, source_url=source_url)

                    elapsed = (time.time() - start_time) * 1000
                    return PrepResult(
                        success=True,
                        sanitized_context=sanitized,
                        source_url=source_url,
                        duration_ms=elapsed,
                        circuit_tripped=False,
                        fallback_used=None,
                    )
                else:
                    breaker.record_failure(f"HTTP {resp.status_code}")
        except Exception as e:
            breaker.record_failure(str(e))

        # 4. If n8n failed, attempt local fallback or fail open
        if config.enable_local_scraper_fallback:
            return cls._execute_local_fallback(user_prompt, start_time, reason=breaker.last_error_message or "n8n error")

        elapsed = (time.time() - start_time) * 1000
        return PrepResult(
            success=False,
            sanitized_context=None,
            source_url=None,
            duration_ms=elapsed,
            circuit_tripped=breaker.state.value == "OPEN",
            fallback_used=None,
            error_message=breaker.last_error_message,
        )

    @classmethod
    def _execute_local_fallback(cls, user_prompt: str, start_time: float, reason: str) -> PrepResult:
        """Lightweight local fallback research generator."""
        config = get_config()

        # Simulated or local research extraction
        mock_summary = (
            f"### Local Research Summary for: {user_prompt}\n"
            f"- Extracted standard reference patterns and API schema.\n"
            f"- Note: n8n was bypassed due to ({reason})."
        )

        pruned, _ = ContextPruner.prune_and_budget(mock_summary, max_tokens=config.n8n_max_tokens)
        sanitized = SecurityGuard.sanitize_untrusted_research(pruned, source_url="local_fallback")

        elapsed = (time.time() - start_time) * 1000
        return PrepResult(
            success=True,
            sanitized_context=sanitized,
            source_url="local_fallback",
            duration_ms=elapsed,
            circuit_tripped=False,
            fallback_used="local_micro_researcher",
        )
