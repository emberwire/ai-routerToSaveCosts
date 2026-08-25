import os
import sys
import shutil
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from ai_router.engines.base import BaseExecutionEngine, ExecutionResult, EngineStatus
from ai_router.config import get_config
from ai_router.gateway import CloudflareAIGateway
from ai_router.prompt_transformer import TransformedPromptPayload


class ClaudeCodeEngine(BaseExecutionEngine):
    """
    Claude Code CLI Execution Engine:
    - Resolves `/opt/homebrew/bin/claude` or system PATH.
    - Defaults to Claude Opus with Effort 5 Extra.
    - Passes identified model via environment and prompt directives.
    - Default Interactive TTY Handover: Uses `subprocess.run` with stdio connected so developer retains full interactive terminal.
    - One-Shot / Script Mode: Invokes `claude -p "<prompt>"` capturing output.
    - Automatically injects Cloudflare AI Gateway URL into `ANTHROPIC_BASE_URL` when enabled.
    """

    def __init__(self):
        super().__init__(name="claude")

    def get_binary_path(self) -> Optional[str]:
        config = get_config()
        if config.claude_binary_path and Path(config.claude_binary_path).exists():
            return config.claude_binary_path
        
        if Path("/opt/homebrew/bin/claude").exists():
            return "/opt/homebrew/bin/claude"

        return shutil.which("claude")

    def is_available(self) -> bool:
        return self.get_binary_path() is not None

    def execute(
        self,
        payload: TransformedPromptPayload,
        interactive: bool = True,
        model_name: Optional[str] = None,
        effort_level: int = 5,
    ) -> ExecutionResult:
        start_time = time.time()
        binary = self.get_binary_path()
        config = get_config()

        if not binary:
            return ExecutionResult(
                status=EngineStatus.ERROR,
                engine_name="claude",
                output_text="",
                exit_code=127,
                duration_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                error_message="Claude Code binary not found (expected /opt/homebrew/bin/claude or in PATH).",
            )

        target_model = model_name or config.claude_model
        effort = effort_level or config.claude_default_effort

        # Layer the effort directive onto the transformer's system instruction
        system_prompt = payload.system_instruction or ""
        if effort >= 5:
            effort_directive = (
                f'<effort_budget level="{effort}">Apply maximum exhaustive verification, '
                f'step-by-step reasoning, and edge-case validation.</effort_budget>'
            )
            system_prompt = f"{system_prompt}\n{effort_directive}" if system_prompt else effort_directive

        assembled_prompt = payload.formatted_prompt

        # Prepare Environment
        env = os.environ.copy()
        env["ANTHROPIC_MODEL"] = target_model
        gateway_meta = None

        if config.enable_cf_gateway and config.cf_account_id and config.cf_gateway_id:
            cf_endpoint = CloudflareAIGateway.get_provider_endpoint("anthropic")
            if cf_endpoint:
                env["ANTHROPIC_BASE_URL"] = cf_endpoint
                gateway_meta = {"provider": "anthropic", "gateway_url": cf_endpoint}

        if config.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

        # Interactive Mode: Handover terminal control to Claude Code
        if interactive:
            print(f"\n[AI Router] 🚀 Handing off to Claude Code ({binary}) [Model: {target_model} | Effort: {effort}/5 Extra]...\n")
            args = [binary, "--model", target_model]
            if system_prompt:
                args += ["--append-system-prompt", system_prompt]
            args.append(assembled_prompt)
            try:
                result = subprocess.run(args, env=env)
                elapsed = (time.time() - start_time) * 1000
                return ExecutionResult(
                    status=EngineStatus.SUCCESS if result.returncode == 0 else EngineStatus.ERROR,
                    engine_name="claude",
                    output_text="Interactive session completed.",
                    exit_code=result.returncode,
                    duration_ms=elapsed,
                    input_tokens=max(10, len(assembled_prompt.split())),
                    output_tokens=0,
                    cost_usd=0.0,
                    gateway_metadata=gateway_meta,
                )
            except KeyboardInterrupt:
                return ExecutionResult(
                    status=EngineStatus.INTERRUPTED,
                    engine_name="claude",
                    output_text="Session interrupted by user.",
                    exit_code=130,
                    duration_ms=(time.time() - start_time) * 1000,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                )
            except Exception as e:
                return ExecutionResult(
                    status=EngineStatus.ERROR,
                    engine_name="claude",
                    output_text="",
                    exit_code=1,
                    duration_ms=(time.time() - start_time) * 1000,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    error_message=str(e),
                )

        # One-Shot Mode (-p)
        else:
            args = [binary, "-p", "--model", target_model]
            if system_prompt:
                args += ["--append-system-prompt", system_prompt]
            args.append(assembled_prompt)
            try:
                result = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
                elapsed = (time.time() - start_time) * 1000
                output = result.stdout or result.stderr
                return ExecutionResult(
                    status=EngineStatus.SUCCESS if result.returncode == 0 else EngineStatus.ERROR,
                    engine_name="claude",
                    output_text=output,
                    exit_code=result.returncode,
                    duration_ms=elapsed,
                    input_tokens=max(10, len(assembled_prompt.split())),
                    output_tokens=max(10, len(output.split())),
                    cost_usd=0.0,
                    error_message=result.stderr if result.returncode != 0 else None,
                    gateway_metadata=gateway_meta,
                )
            except Exception as e:
                return ExecutionResult(
                    status=EngineStatus.ERROR,
                    engine_name="claude",
                    output_text="",
                    exit_code=1,
                    duration_ms=(time.time() - start_time) * 1000,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    error_message=str(e),
                )
