from typing import List, Dict, Any, Optional
import time
import os
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.markdown import Markdown
from rich.align import Align
from rich.progress import Progress, SpinnerColumn, TextColumn
from ai_router.classifier import ClassificationResult
from ai_router.telemetry_roi import CumulativeStats, TelemetryROI
from ai_router.diagnostics import DiagnosticCheck, Diagnostics
from ai_router.config import get_config
from ai_router.circuit_breaker import get_circuit_breaker
from ai_router.engines.registry import get_engine_registry


console = Console()

ASCII_LOGO = """[bold cyan]
  █████╗ ██╗    ██████╗  ██████╗ ██╗   ██╗████████╗███████╗██████╗ 
 ██╔══██╗██║    ██╔══██╗██╔═══██╗██║   ██║╚══██╔══╝██╔════╝██╔══██╗
 ███████║██║    ██████╔╝██║   ██║██║   ██║   ██║   █████╗  ██████╔╝
 ██╔══██║██║    ██╔══██╗██║   ██║██║   ██║   ██║   ██╔══╝  ██╔══██╗
 ██║  ██║██║    ██║  ██║╚██████╔╝╚██████╔╝   ██║   ███████╗██║  ██║
 ╚═╝  ╚═╝╚═╝    ╚═╝  ╚═╝ ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝╚═╝  ╚═╝[/bold cyan]
[bold white]  Enterprise Multi-Model Prompt Router & Context-Budgeting Orchestrator[/bold white] [dim]v4.0[/dim]
"""


def print_banner():
    banner_text = (
        "[bold cyan]⚡ AI-ROUTED CLI AGENT[/bold cyan] [bold white]v4.0[/bold white] "
        "[dim]| Multi-Model Router & Enterprise Orchestrator[/dim]"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def render_launcher_screen():
    """
    Renders an executive-grade, rich TUI Launcher Dashboard.
    Displays live engine statuses, circuit health, telemetry summary, and interactive quick actions.
    """
    config = get_config()
    stats = TelemetryROI.load_stats()
    breaker = get_circuit_breaker()
    registry = get_engine_registry()
    statuses = registry.get_engine_statuses()

    console.clear()
    console.print(Align.center(ASCII_LOGO))

    # Row 1: System Status & Telemetry Cards
    engine_badges = []
    if statuses.get("claude"):
        engine_badges.append(f"[bold magenta]🟣 Claude Code[/bold magenta] [green]●[/green] [dim]({config.claude_model} | Effort: {config.claude_default_effort}/5 Extra)[/dim]")
    else:
        engine_badges.append("[dim magenta]🟣 Claude[/dim magenta] [dim yellow]○[/dim yellow]")

    if statuses.get("gemini"):
        engine_badges.append(f"[bold blue]🔵 Gemini 3.7[/bold blue] [green]●[/green] [dim]({config.gemini_model})[/dim]")
    else:
        engine_badges.append("[dim blue]🔵 Gemini[/dim blue] [dim yellow]○[/dim yellow]")

    if statuses.get("codex"):
        engine_badges.append(f"[bold green]🟢 Codex/o3[/bold green] [green]●[/green] [dim]({config.codex_model})[/dim]")
    else:
        engine_badges.append("[dim green]🟢 Codex[/dim green] [dim yellow]○[/dim yellow]")

    engines_card = Panel(
        "\n".join(engine_badges),
        title="[bold]⚡ Active Engines & Defaults[/bold]",
        border_style="cyan",
    )

    breaker_color = "green" if breaker.state.value == "CLOSED" else "red"
    n8n_status_str = (
        f"[bold]n8n Pipeline:[/bold] [cyan]{config.n8n_webhook_url or 'Disabled'}[/cyan]\n"
        f"[bold]Circuit Breaker:[/bold] [{breaker_color}]● {breaker.state.value}[/{breaker_color}]\n"
        f"[bold]Fail-Open Guard:[/bold] [green]Active (Zero Block)[/green]"
    )
    resilience_card = Panel(
        n8n_status_str,
        title="[bold]🔄 Prep & Resilience[/bold]",
        border_style="blue",
    )

    savings_str = (
        f"[bold]Commands Routed:[/bold] [white]{stats.total_commands}[/white]\n"
        f"[bold]Tokens Spared:[/bold] [bold green]{stats.context_tokens_spared:,}[/bold green]\n"
        f"[bold]Est. Savings:[/bold] [bold green]${stats.dollar_savings_usd:.4f}[/bold green]"
    )
    roi_card = Panel(
        savings_str,
        title="[bold]📊 Cumulative ROI[/bold]",
        border_style="green",
    )

    console.print(Columns([engines_card, resilience_card, roi_card], equal=True))
    console.print()

    # Menu Options Table
    menu_table = Table(title="🎛️  COMMAND & NAVIGATION MENU", border_style="bright_blue", show_header=True, header_style="bold cyan")
    menu_table.add_column("Key", style="bold yellow", justify="center", width=6)
    menu_table.add_column("Action", style="bold white", width=26)
    menu_table.add_column("Description", style="dim")

    menu_table.add_row("1", "🚀 Run AI Task Prompt", "Execute a task with automatic intent evaluation and n8n prep")
    menu_table.add_row("2", "🟣 Launch Claude Code (Opus)", "Interactive TTY terminal coding session with Claude Opus (Effort 5)")
    menu_table.add_row("3", "🔵 Launch Gemini Assistant", "Large context (2M tokens) live streaming coding assistant (Gemini 3.7)")
    menu_table.add_row("4", "🟢 Launch Codex / o-series", "OpenAI o3-mini/o1 deep reasoning execution session")
    menu_table.add_row("5", "🩺 System Diagnostics", "Run 1-click self-healing health check (ai doctor)")
    menu_table.add_row("6", "📊 ROI & Telemetry Report", "Detailed token compression and dollar savings dashboard (ai roi)")
    menu_table.add_row("7", "🧪 Routing Benchmark Evals", "Run synthetic test harness to verify routing precision (ai eval)")
    menu_table.add_row("8", "⚙️  Configure Settings", "Manage models (Opus/Sonnet/Gemini), API keys, webhooks, and defaults")
    menu_table.add_row("Q", "🚪 Exit", "Exit AI Router CLI")

    console.print(menu_table)
    console.print()


def print_intent_badge(res: ClassificationResult, engine: str):
    intent_colors = {
        "EXECUTE_ONLY": "green",
        "PREP_AND_EXECUTE": "magenta",
        "RESEARCH_ONLY": "yellow",
    }
    color = intent_colors.get(res.intent, "white")
    fast_badge = "[bold yellow]⚡ FAST PATH[/bold yellow] | " if res.is_fast_path else ""
    effort_badge = f"[bold red]⚡ Effort: {res.effort_level}/5 (EXTRA)[/bold red]" if res.effort_level >= 5 else f"Effort: {res.effort_level}/5"
    
    table = Table.grid(padding=(0, 2))
    table.add_row(
        f"[{color}]🎯 Intent: [bold]{res.intent}[/bold][/{color}]",
        f"[blue]🚀 Engine: [bold]{engine.upper()}[/bold] [cyan]({res.suggested_model})[/cyan][/blue]",
        f"[magenta]{effort_badge}[/magenta]",
        f"[dim]({fast_badge}{res.evaluation_duration_ms:.1f}ms)[/dim]",
    )
    console.print(Panel(table, border_style=color, title="[bold]Routing & Model Decision[/bold]"))


def print_research_panel(markdown_content: str, source_url: Optional[str] = None):
    source_tag = f" [dim]({source_url})[/dim]" if source_url else ""
    md = Markdown(markdown_content)
    console.print(Panel(md, title=f"[bold magenta]📚 Pre-Fetched Context{source_tag}[/bold magenta]", border_style="magenta"))


def print_roi_dashboard(stats: CumulativeStats):
    table = Table(title="📊 AI Router ROI & Token Savings Telemetry", border_style="green")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="bold white")
    table.add_column("Business & AI Engineering Impact", style="dim")

    table.add_row("Total Commands Executed", str(stats.total_commands), "All terminal requests routed")
    table.add_row("Prep Invocations (n8n)", str(stats.prep_invocations), "Heavy research tasks offloaded")
    table.add_row("Execute Only (Direct)", str(stats.execute_only_count), "Fast-path & local direct edits")
    table.add_row("Tokens Spared / Compressed", f"{stats.context_tokens_spared:,} tokens", "Saved from frontier context window")
    table.add_row("Net Dollar Savings (USD)", f"${stats.dollar_savings_usd:.4f}", "Based on Claude 3.5 Sonnet token pricing")
    table.add_row("Edge Cache Hits", str(stats.cache_hits), "Zero-latency Cloudflare edge hits")
    table.add_row("Circuit Breaker Trips", str(stats.circuit_trips), "Fail-open activations (zero dev block)")

    console.print(table)


def print_diagnostics_table(checks: List[DiagnosticCheck]):
    table = Table(title="🩺 AI Doctor - System Diagnostic Report", border_style="blue")
    table.add_column("Category", style="cyan")
    table.add_column("Check / Layer", style="bold white")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    status_styles = {
        "PASS": "[bold green] PASS [/bold green]",
        "WARN": "[bold yellow] WARN [/bold yellow]",
        "FAIL": "[bold red] FAIL [/bold red]",
        "INFO": "[bold blue] INFO [/bold blue]",
    }

    for c in checks:
        badge = status_styles.get(c.status, c.status)
        lat = f" ({c.latency_ms:.0f}ms)" if c.latency_ms else ""
        table.add_row(c.category, c.name, badge, f"{c.message}{lat}")

    console.print(table)


def print_eval_report(report):
    table = Table(title="🧪 AI Router Benchmark & Accuracy Evaluation", border_style="cyan")
    table.add_column("Test Prompt", style="white")
    table.add_column("Category", style="cyan")
    table.add_column("Expected", style="dim")
    table.add_column("Actual", style="bold")
    table.add_column("Model Identified", style="magenta")
    table.add_column("Latency", justify="right")
    table.add_column("Result", justify="center")

    for r in report.results:
        res_badge = "[bold green]PASS[/bold green]" if r["pass"] else "[bold red]FAIL[/bold red]"
        table.add_row(
            r["prompt"][:40] + "...",
            r["category"],
            r["expected"],
            r["actual"],
            r.get("model", "opus"),
            f"{r['latency_ms']:.1f}ms",
            res_badge,
        )

    console.print(table)
    summary_panel = (
        f"[bold]Accuracy:[/bold] [green]{report.accuracy_percentage:.1f}%[/green] "
        f"({report.correct_intents}/{report.total_cases}) | "
        f"[bold]Avg Latency:[/bold] [cyan]{report.avg_latency_ms:.1f}ms[/cyan]"
    )
    console.print(Panel(summary_panel, border_style="green", expand=False))
