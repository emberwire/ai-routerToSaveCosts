import time
import json
import httpx
from typing import Optional, Dict, Any
from ai_router.engines.base import BaseExecutionEngine, ExecutionResult, EngineStatus
from ai_router.config import get_config
from ai_router.gateway import CloudflareAIGateway
from ai_router.reasoning_budgeter import ReasoningBudgeter
from ai_router.stream_renderer import StreamRenderer


class GeminiExecutionEngine(BaseExecutionEngine):
    """
    Gemini 2.5 Pro / Flash Execution Engine:
    - Supports large context window analysis (up to 2M tokens).
    - Streams code output live with syntax highlighting.
    - Proxies through Cloudflare AI Gateway when enabled.
    """

    def __init__(self):
        super().__init__(name="gemini")

    def is_available(self) -> bool:
        config = get_config()
        return bool(config.gemini_api_key)

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
                engine_name="gemini",
                output_text="",
                exit_code=1,
                duration_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                error_message="GEMINI_API_KEY is not configured.",
            )

        budget = ReasoningBudgeter.get_budget("gemini", complexity_score)
        model = config.gemini_exec_model if complexity_score >= 3 else config.gemini_model

        # Assemble prompt contents
        user_parts = []
        if context:
            user_parts.append(f"### Reference Context:\n{context}\n\n")
        user_parts.append(f"### Task Objective:\n{prompt}")
        full_content = "".join(user_parts)

        # Build URL (Direct or Cloudflare AI Gateway)
        if config.enable_cf_gateway and config.cf_account_id and config.cf_gateway_id:
            base_url = CloudflareAIGateway.get_provider_endpoint("google-ai-studio")
            url = f"{base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse"
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={config.gemini_api_key}&alt=sse"

        payload = {
            "contents": [{"parts": [{"text": full_content}]}],
            "generationConfig": {
                "temperature": 0.2,
            }
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if budget.gemini_thinking_budget > 0:
            payload["generationConfig"]["thinkingConfig"] = {"thinking_budget": budget.gemini_thinking_budget}

        headers = {"Content-Type": "application/json"}
        if config.enable_cf_gateway:
            headers.update(CloudflareAIGateway.get_gateway_headers())

        output_chunks = []
        ttft_recorded = False
        ttft_ms = 0.0

        try:
            with httpx.Client(timeout=60.0) as client:
                with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        err_text = response.read().decode()
                        return ExecutionResult(
                            status=EngineStatus.ERROR,
                            engine_name="gemini",
                            output_text="",
                            exit_code=response.status_code,
                            duration_ms=(time.time() - start_time) * 1000,
                            input_tokens=0,
                            output_tokens=0,
                            cost_usd=0.0,
                            error_message=f"Gemini API returned {response.status_code}: {err_text}",
                        )

                    # Stream tokens
                    renderer = StreamRenderer(title=f"Gemini ({model}) Stream")
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        
                        if not ttft_recorded:
                            ttft_ms = (time.time() - start_time) * 1000
                            ttft_recorded = True

                        raw_json = line[6:].strip()
                        try:
                            chunk = json.loads(raw_json)
                            text_part = chunk["candidates"][0]["content"]["parts"][0].get("text", "")
                            if text_part:
                                output_chunks.append(text_part)
                                renderer.update(text_part)
                        except Exception:
                            continue

                    renderer.finish()

            full_output = "".join(output_chunks)
            elapsed = (time.time() - start_time) * 1000
            in_tokens = max(10, len(full_content.split()))
            out_tokens = max(10, len(full_output.split()))

            return ExecutionResult(
                status=EngineStatus.SUCCESS,
                engine_name="gemini",
                output_text=full_output,
                exit_code=0,
                duration_ms=elapsed,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                cost_usd=0.0,  # Free Google tier
                gateway_metadata={"ttft_ms": ttft_ms},
            )

        except Exception as e:
            return ExecutionResult(
                status=EngineStatus.ERROR,
                engine_name="gemini",
                output_text="",
                exit_code=1,
                duration_ms=(time.time() - start_time) * 1000,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                error_message=str(e),
            )
