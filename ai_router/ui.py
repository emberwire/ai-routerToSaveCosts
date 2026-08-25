from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from ai_router.classifier import ClassificationResult
from ai_router.telemetry_roi import CumulativeStats
from ai_router.diagnostics import DiagnosticCheck


console = Console()


def print_banner():
    banner_text = (
        "[bold cyan]⚡ AI-ROUTED CLI AGENT[/bold cyan] [bold white]v4.0[/bold white] "
        "[dim]| Multi-Model Router & Enterprise Orchestrator[/dim]"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def print_intent_badge(res: ClassificationResult, engine: str):
    intent_colors = {
        "EXECUTE_ONLY": "green",
        "PREP_AND_EXECUTE": "magenta",
        "RESEARCH_ONLY": "yellow",
    }
    color = intent_colors.get(res.intent, "white")
    fast_badge = "[bold yellow]⚡ FAST PATH[/bold yellow] | " if res.is_fast_path else ""
    
    table = Table.grid(padding=(0, 2))
    table.add_row(
        f"[{color}]🎯 Intent: [bold]{res.intent}[/bold][/{color}]",
        f"[cyan]🎚️ Complexity: {res.complexity_score}/5[/cyan]",
        f"[blue]🚀 Engine: [bold]{engine.upper()}[/bold][/blue]",
        f"[dim]({fast_badge}{res.evaluation_duration_ms:.1f}ms)[/dim]",
    )
    console.print(Panel(table, border_style=color, title="[bold]Routing Decision[/bold]"))


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
    table.add_column("Score", justify="center")
    table.add_column("Latency", justify="right")
    table.add_column("Result", justify="center")

    for r in report.results:
        res_badge = "[bold green]PASS[/bold green]" if r["pass"] else "[bold red]FAIL[/bold red]"
        table.add_row(
            r["prompt"][:45] + "...",
            r["category"],
            r["expected"],
            r["actual"],
            f"{r['complexity']}/5",
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
