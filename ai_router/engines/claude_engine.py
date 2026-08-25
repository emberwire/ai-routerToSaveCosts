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
        prompt: str,
        context: Optional[str] = None,
        interactive: bool = True,
        complexity_score: int = 5,
        system_instruction: Optional[str] = None,
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

        # Assemble full payload with effort directives
        effort_directive = f"\n<effort_budget level=\"{effort}\">Apply maximum exhaustive verification, step-by-step reasoning, and edge-case validation.</effort_budget>\n" if effort >= 5 else ""

        assembled_prompt = prompt
        if context:
            assembled_prompt = f"{context}\n\n{effort_directive}<user_prompt>\n{prompt}\n</user_prompt>"
        elif effort_directive:
            assembled_prompt = f"{effort_directive}\n{prompt}"

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
            args = [binary, assembled_prompt]
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
            args = [binary, "-p", assembled_prompt]
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
