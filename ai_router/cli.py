import sys
import os
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt
from ai_router.config import get_config, set_config
from ai_router.api import AIRouter, RouterEvent
from ai_router.telemetry_roi import TelemetryROI
from ai_router.diagnostics import Diagnostics
from ai_router.eval_harness import EvalHarness
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
    """
    Thin Rich-rendering consumer of `AIRouter.route()`. All orchestration now lives
    in `ai_router.api.AIRouter`; this function only turns `RouterEvent`s into the
    exact console output the CLI has always produced, plus a final render of the
    returned `RouteResult`.
    """
    print_banner()

    # Preserve exact ambient-config semantics: `run_pipeline` historically read/mutated
    # the process-wide singleton (e.g. `--offline` stuck for the rest of the process).
    router = AIRouter(config=get_config())

    prep: Optional[bool] = None
    if force_prep:
        prep = True
    elif bypass_prep:
        prep = False

    status = console.status(
        "[bold cyan]⚡ Calling n8n Research Pipeline... Fetching & condensing context...[/bold cyan]",
        spinner="dots",
    )

    def on_event(event: RouterEvent) -> None:
        if event.kind == "dlp_violation":
            violations = event.data["violations"]
            console.print(
                f"[bold red]🛡️  CSO DLP Alert:[/bold red] Detected sensitive patterns: "
                f"{', '.join(violations)}. Sanitizing before network egress."
            )
        elif event.kind == "classified":
            print_intent_badge(event.data["classification"], event.data["engine"])
        elif event.kind == "prep_start":
            status.start()
        elif event.kind == "prep_complete":
            status.stop()
            print_research_panel(event.data["markdown"], event.data.get("source_url"))
        elif event.kind == "prep_failed":
            status.stop()
            console.print(
                f"[yellow]⚠️ Prep pipeline unavailable ({event.data.get('error_message')}) "
                f"-> Failing open to direct execution.[/yellow]"
            )
        elif event.kind == "research_only":
            console.print("[bold green]ℹ️ Pure research mode:[/bold green] No code execution requested.")
        elif event.kind == "execution_complete" and event.data.get("mock"):
            result = event.data["result"]
            console.print(
                f"\n[bold green]✅ Simulation Complete "
                f"({event.data['engine'].upper()} - {event.data['model']}) "
                f"[Effort: {event.data['effort']}/5 Extra][/bold green]"
            )
            console.print(result.output_text)

    router.route(
        prompt=prompt,
        engine=forced_engine,
        prep=prep,
        interactive=interactive,
        mock=mock_mode,
        offline=offline_mode,
        on_event=on_event,
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
