import sys
import time
from typing import Optional
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown


class StreamRenderer:
    """
    Live Markdown Streaming Engine with Syntax Highlighting and TTFT HUD.
    """

    def __init__(self, title: str = "AI Stream"):
        self.title = title
        self.console = Console()
        self.accumulated_text = ""
        self.live: Optional[Live] = None
        self.token_count = 0
        self.start_time = time.time()
        self.ttft: Optional[float] = None

    def update(self, token_chunk: str):
        if not self.ttft:
            self.ttft = (time.time() - self.start_time) * 1000

        self.accumulated_text += token_chunk
        self.token_count += max(1, len(token_chunk.split()))

        # Live rendering
        if self.live is None:
            self.live = Live(
                self._render_panel(),
                console=self.console,
                refresh_per_second=10,
                transient=False,
            )
            self.live.start()
        else:
            self.live.update(self._render_panel())

    def _render_panel(self) -> Panel:
        elapsed = max(0.001, time.time() - self.start_time)
        tps = self.token_count / elapsed
        ttft_str = f"{self.ttft:.0f}ms" if self.ttft else "..."

        subtitle = f"[cyan]TTFT: {ttft_str}[/cyan] | [green]{tps:.1f} tokens/s[/green] | [yellow]Tokens: {self.token_count}[/yellow]"
        md = Markdown(self.accumulated_text or "...")
        return Panel(md, title=f"[bold blue]{self.title}[/bold blue]", subtitle=subtitle, border_style="blue")

    def finish(self):
        if self.live:
            self.live.update(self._render_panel())
            self.live.stop()
            self.live = None
