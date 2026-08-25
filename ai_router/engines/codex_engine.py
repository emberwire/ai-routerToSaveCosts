import time
import json
import httpx
from typing import Optional, Dict, Any
from ai_router.engines.base import BaseExecutionEngine, ExecutionResult, EngineStatus
from ai_router.config import get_config
from ai_router.gateway import CloudflareAIGateway
from ai_router.reasoning_budgeter import ReasoningBudgeter
from ai_router.stream_renderer import StreamRenderer


class CodexExecutionEngine(BaseExecutionEngine):
    """
    OpenAI Codex / o-series Execution Engine:
    - Supports `o3-mini`, `o1`, and `gpt-4o`.
    - Implements dynamic `reasoning_effort` tuning (low/medium/high).
    - Streams output with live code block rendering.
    - Proxies through Cloudflare AI Gateway when configured.
    """

    def __init__(self):
        super().__init__(name="codex")

    def is_available(self) -> bool:
        config = get_config()
        return bool(config.openai_api_key)

    def execute(
        self,
        prompt: str,
        context: Optional[str] = None,
        interactive: bool = True,
        complexity_score: int = 3,
        system_instruction: Optional[str] = None,
    ) -> ExecutionResult:
        start_time = time.time()
        config = get_config()

        if not self.is_available() and not config.offline_mode:
            return ExecutionResult(
                status=EngineStatus.ERROR,
                engine_name="codex",
                output_text="",
                exit_code=1,
                duration_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                error_message="OPENAI_API_KEY is not configured.",
            )

        budget = ReasoningBudgeter.get_budget("codex", complexity_score)
        model = config.codex_model

        # Build messages payload
        messages = []
        if system_instruction and not model.startswith("o1"):
            # o1 doesn't support system, o3-mini supports developer
            role = "developer" if model.startswith("o3") else "system"
            messages.append({"role": role, "content": system_instruction})

        content_parts = []
        if context:
            content_parts.append(f"### Reference Context:\n{context}\n\n")
        content_parts.append(f"### Task:\n{prompt}")
        messages.append({"role": "user", "content": "".join(content_parts)})

        # Build endpoint URL
        if config.enable_cf_gateway and config.cf_account_id and config.cf_gateway_id:
            base_url = CloudflareAIGateway.get_provider_endpoint("openai")
            url = f"{base_url}/chat/completions"
        else:
            url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        # Add reasoning effort for o-series models
        if model.startswith("o3") or model.startswith("o1"):
            payload["reasoning_effort"] = budget.openai_reasoning_effort

        headers = {
            "Authorization": f"Bearer {config.openai_api_key}",
            "Content-Type": "application/json",
        }
        if config.enable_cf_gateway:
            headers.update(CloudflareAIGateway.get_gateway_headers())

        output_chunks = []
        ttft_ms = 0.0
        ttft_recorded = False

        try:
            with httpx.Client(timeout=60.0) as client:
                with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        err_text = response.read().decode()
                        return ExecutionResult(
                            status=EngineStatus.ERROR,
                            engine_name="codex",
                            output_text="",
                            exit_code=response.status_code,
                            duration_ms=(time.time() - start_time) * 1000,
                            input_tokens=0,
                            output_tokens=0,
                            cost_usd=0.0,
                            error_message=f"OpenAI API returned {response.status_code}: {err_text}",
                        )

                    renderer = StreamRenderer(title=f"Codex / OpenAI ({model}) Stream")
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break

                        if not ttft_recorded:
                            ttft_ms = (time.time() - start_time) * 1000
                            ttft_recorded = True

                        try:
                            chunk = json.loads(raw)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                output_chunks.append(delta)
                                renderer.update(delta)
                        except Exception:
                            continue

                    renderer.finish()

            full_output = "".join(output_chunks)
            elapsed = (time.time() - start_time) * 1000
            in_tokens = max(10, len(str(messages).split()))
            out_tokens = max(10, len(full_output.split()))

            # Approx cost for o3-mini ($1.10 / 1M in, $4.40 / 1M out)
            cost = (in_tokens / 1_000_000 * 1.10) + (out_tokens / 1_000_000 * 4.40)

            return ExecutionResult(
                status=EngineStatus.SUCCESS,
                engine_name="codex",
                output_text=full_output,
                exit_code=0,
                duration_ms=elapsed,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost_usd=cost,
                gateway_metadata={"ttft_ms": ttft_ms},
            )

        except Exception as e:
            return ExecutionResult(
                status=EngineStatus.ERROR,
                engine_name="codex",
                output_text="",
                exit_code=1,
                duration_ms=(time.time() - start_time) * 1000,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                error_message=str(e),
            )
