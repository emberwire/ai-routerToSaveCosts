import sys
import os
import time
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt
from ai_router.config import get_config, set_config
from ai_router.security_guard import SecurityGuard
from ai_router.audit_logger import AuditLogger
from ai_router.context_scanner import ContextScanner
from ai_router.classifier import IntentClassifier
from ai_router.n8n_pipeline import N8nResearchPipeline
from ai_router.prompt_transformer import CanonicalPromptAST, PromptTransformer
from ai_router.engines.registry import get_engine_registry
from ai_router.telemetry_roi import TelemetryROI
from ai_router.diagnostics import Diagnostics
from ai_router.eval_harness import EvalHarness
from ai_router.mock_services import MockServices
from ai_router.circuit_breaker import get_circuit_breaker
from ai_router.ui import (
    console,
    print_banner,
    render_launcher_screen,
    print_intent_badge,
    print_research_panel,
    print_roi_dashboard,
    print_diagnostics_table,
    print_eval_report,
)

app = typer.Typer(
    name="ai",
    help="AI-Routed CLI Agent - Intelligent, secure multi-model prompt router and orchestrator.",
    no_args_is_help=False,
)

KNOWN_SUBCOMMANDS = {"doctor", "roi", "eval", "config", "run", "launcher", "--help", "-h"}


def run_pipeline(
    prompt: str,
    forced_engine: Optional[str] = None,
    force_prep: bool = False,
    bypass_prep: bool = False,
    interactive: bool = True,
    mock_mode: bool = False,
    offline_mode: bool = False,
):
    config = get_config()
    if offline_mode:
        config.offline_mode = True

    start_time = time.time()
    print_banner()

    # Step 1: CSO Local Data Loss Prevention (DLP) Scan
    dlp_violations = []
    sanitized_prompt = prompt
    if config.enable_dlp_scanner:
        dlp_res = SecurityGuard.scan_dlp(prompt, redact=True)
        if not dlp_res.is_clean:
            dlp_violations = dlp_res.violations
            console.print(f"[bold red]🛡️  CSO DLP Alert:[/bold red] Detected sensitive patterns: {', '.join(dlp_violations)}. Sanitizing before network egress.")
            sanitized_prompt = dlp_res.sanitized_text

    # Step 2: Local Repo Micro-Fingerprint Scan (<10ms)
    repo_summary = ContextScanner.get_summary_prompt_context()

    # Step 3: Intent & Complexity & Model Classification
    if mock_mode:
        classification = MockServices.mock_classification(sanitized_prompt, force_engine=forced_engine)
    else:
        classification = IntentClassifier.evaluate(sanitized_prompt, repo_context=repo_summary, force_engine=forced_engine)

    # Resolve target engine & model
    target_engine_name = forced_engine or classification.suggested_engine or config.default_engine
    if target_engine_name == "auto":
        target_engine_name = classification.suggested_engine or "claude"

    print_intent_badge(classification, target_engine_name)

    # Determine whether to run prep pipeline
    should_prep = (classification.intent == "PREP_AND_EXECUTE" or force_prep) and not bypass_prep

    prep_context_md = None
    source_url = None
    raw_len = 0
    pruned_tokens = 0
    circuit_tripped = False

    # Step 4: Research Pipeline (if required)
    if should_prep:
        with console.status("[bold cyan]⚡ Calling n8n Research Pipeline... Fetching & condensing context...[/bold cyan]", spinner="dots"):
            if mock_mode:
                prep_result = MockServices.mock_n8n_prep(sanitized_prompt)
            else:
                prep_result = N8nResearchPipeline.execute_prep(sanitized_prompt, repo_context=repo_summary)

        if prep_result.success and prep_result.sanitized_context:
            prep_context_md = prep_result.sanitized_context.quarantined_markdown
            source_url = prep_result.source_url
            raw_len = len(prep_result.sanitized_context.raw_text)
            pruned_tokens = max(10, len(prep_context_md.split()))
            print_research_panel(prep_context_md, source_url)
        else:
            circuit_tripped = prep_result.circuit_tripped
            console.print(f"[yellow]⚠️ Prep pipeline unavailable ({prep_result.error_message}) -> Failing open to direct execution.[/yellow]")

    elif classification.intent == "RESEARCH_ONLY":
        # Pure information display
        console.print("[bold green]ℹ️ Pure research mode:[/bold green] No code execution requested.")
        return

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

    if mock_mode:
        exec_result = MockServices.mock_execution(
            target_engine_name,
            sanitized_prompt,
            prep_context_md,
            model=classification.suggested_model,
            effort=classification.effort_level,
        )
        console.print(f"\n[bold green]✅ Simulation Complete ({target_engine_name.upper()} - {classification.suggested_model}) [Effort: {classification.effort_level}/5 Extra][/bold green]")
        console.print(exec_result.output_text)
    else:
        exec_result = engine_instance.execute(
            prompt=sanitized_prompt,
            context=prep_context_md,
            interactive=interactive,
            complexity_score=classification.complexity_score,
            system_instruction=payload.system_instruction,
            model_name=classification.suggested_model,
            effort_level=classification.effort_level,
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


@app.command(name="run", hidden=True)
def run_command(
    prompt: str = typer.Argument(..., help="The task prompt to execute"),
    engine: Optional[str] = typer.Option(None, "--engine", "-e", help="Execution engine: claude, gemini, codex, auto"),
    prep: bool = typer.Option(False, "--prep", help="Force invoke research prep pipeline"),
    no_prep: bool = typer.Option(False, "--no-prep", help="Bypass research prep pipeline"),
    interactive: bool = typer.Option(True, "--interactive/--non-interactive", help="Run interactive TTY REPL session"),
    mock: bool = typer.Option(False, "--mock", help="Run in offline simulation/demo mode"),
    offline: bool = typer.Option(False, "--offline", help="Enforce local-only air-gap mode"),
):
    """Executes a prompt through the AI router."""
    run_pipeline(
        prompt=prompt,
        forced_engine=engine,
        force_prep=prep,
        bypass_prep=no_prep,
        interactive=interactive,
        mock_mode=mock,
        offline_mode=offline,
    )


@app.command(name="doctor")
def doctor_command():
    """
    Run 1-click self-healing health checks for all layers.
    """
    print_banner()
    checks = Diagnostics.run_all_checks()
    print_diagnostics_table(checks)


@app.command(name="roi")
def roi_command():
    """
    Display cumulative token savings, net dollar savings, and telemetry.
    """
    print_banner()
    stats = TelemetryROI.load_stats()
    print_roi_dashboard(stats)


@app.command(name="eval")
def eval_command():
    """
    Run automated accuracy and benchmark evaluation harness.
    """
    print_banner()
    with console.status("[bold cyan]Running synthetic benchmark test cases...[/bold cyan]", spinner="dots"):
        report = EvalHarness.run_eval()
    print_eval_report(report)


@app.command(name="config")
def config_command(
    set_engine: Optional[str] = typer.Option(None, "--default-engine", help="Set default engine (claude, gemini, codex, auto)"),
    set_claude_model: Optional[str] = typer.Option(None, "--claude-model", help="Set Claude model (e.g. claude-opus-5, claude-sonnet-5)"),
    set_gemini_model: Optional[str] = typer.Option(None, "--gemini-model", help="Set Gemini model (e.g. gemini-2.5-flash, gemini-2.5-pro)"),
    set_n8n: Optional[str] = typer.Option(None, "--n8n-url", help="Set n8n webhook URL"),
    set_cf_gateway: Optional[bool] = typer.Option(None, "--enable-gateway", help="Toggle Cloudflare AI Gateway"),
):
    """
    View or modify AI Router configurations.
    """
    print_banner()
    config = get_config()

    if set_engine:
        config.default_engine = set_engine
        console.print(f"[green]✓ Default engine set to:[/green] {set_engine}")

    if set_claude_model:
        config.claude_model = set_claude_model
        console.print(f"[green]✓ Claude model set to:[/green] {set_claude_model}")

    if set_gemini_model:
        config.gemini_model = set_gemini_model
        config.gemini_exec_model = set_gemini_model
        console.print(f"[green]✓ Gemini model set to:[/green] {set_gemini_model}")

    if set_n8n:
        config.n8n_webhook_url = set_n8n
        console.print(f"[green]✓ n8n webhook URL set to:[/green] {set_n8n}")

    if set_cf_gateway is not None:
        config.enable_cf_gateway = set_cf_gateway
        console.print(f"[green]✓ Cloudflare AI Gateway set to:[/green] {set_cf_gateway}")

    from rich.table import Table
    table = Table(title="⚙️ Current Configuration", border_style="cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Default Execution Engine", config.default_engine)
    table.add_row("Claude Code Binary Path", config.claude_binary_path or "None")
    table.add_row("Claude Model (Default)", f"{config.claude_model} (Effort: {config.claude_default_effort}/5 Extra)")
    table.add_row("Gemini Model (Classifier)", config.gemini_model)
    table.add_row("Gemini API Key", "***" if config.gemini_api_key else "[dim]Not Configured (Heuristic fallback)[/dim]")
    table.add_row("OpenAI API Key", "***" if config.openai_api_key else "[dim]Not Configured[/dim]")
    table.add_row("n8n Webhook URL", config.n8n_webhook_url or "None")
    table.add_row("Cloudflare Gateway", "Enabled" if config.enable_cf_gateway else "Disabled")
    table.add_row("DLP Scanner", "Enabled" if config.enable_dlp_scanner else "Disabled")
    table.add_row("Audit Logging", "Enabled" if config.enable_audit_logging else "Disabled")

    console.print(table)


@app.command(name="launcher")
def launcher_command():
    """
    Open the full-screen interactive launcher dashboard.
    """
    run_interactive_wizard()


def run_interactive_wizard():
    render_launcher_screen()
    choice = Prompt.ask("[bold cyan]Select action[/bold cyan] [1-8, Q]", default="1")

    if choice == "1":
        task_prompt = Prompt.ask("\n[bold yellow]Enter your task prompt[/bold yellow]")
        engine_choice = Prompt.ask("Select engine [claude/gemini/codex/auto]", default="claude")
        mock_choice = Prompt.ask("Run with mock simulation? [y/N]", default="n").lower() == "y"
        run_pipeline(prompt=task_prompt, forced_engine=engine_choice, mock_mode=mock_choice)
    elif choice == "2":
        task_prompt = Prompt.ask("\n[bold magenta]Enter Claude prompt (or press Enter for interactive Opus REPL)[/bold magenta]", default="")
        mock_choice = Prompt.ask("Run with mock simulation? [y/N]", default="n").lower() == "y"
        run_pipeline(prompt=task_prompt or "Start interactive coding session", forced_engine="claude", mock_mode=mock_choice)
    elif choice == "3":
        task_prompt = Prompt.ask("\n[bold blue]Enter Gemini prompt (2M context assistant)[/bold blue]")
        mock_choice = Prompt.ask("Run with mock simulation? [y/N]", default="n").lower() == "y"
        run_pipeline(prompt=task_prompt, forced_engine="gemini", mock_mode=mock_choice)
    elif choice == "4":
        task_prompt = Prompt.ask("\n[bold green]Enter Codex / o-series prompt (deep reasoning)[/bold green]")
        mock_choice = Prompt.ask("Run with mock simulation? [y/N]", default="n").lower() == "y"
        run_pipeline(prompt=task_prompt, forced_engine="codex", mock_mode=mock_choice)
    elif choice == "5":
        doctor_command()
    elif choice == "6":
        roi_command()
    elif choice == "7":
        eval_command()
    elif choice == "8":
        config_command(None, None, None, None, None)
    elif choice.upper() == "Q":
        console.print("\n[dim]Goodbye![/dim]\n")
        return
    else:
        console.print("[dim]Unrecognized choice. Exiting launcher.[/dim]")


def cli_entrypoint():
    args = sys.argv[1:]
    if not args:
        run_interactive_wizard()
        return

    first_arg = args[0]
    if first_arg not in KNOWN_SUBCOMMANDS and not first_arg.startswith("-"):
        sys.argv.insert(1, "run")

    app()


if __name__ == "__main__":
    cli_entrypoint()
