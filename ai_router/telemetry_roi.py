import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from ai_router.config import get_config


@dataclass
class CumulativeStats:
    total_commands: int = 0
    prep_invocations: int = 0
    execute_only_count: int = 0
    research_only_count: int = 0
    tokens_compressed: int = 0
    context_tokens_spared: int = 0
    dollar_savings_usd: float = 0.0
    total_duration_ms: float = 0.0
    cache_hits: int = 0
    circuit_trips: int = 0


class TelemetryROI:
    """
    CTO ROI & Savings Telemetry Tracker.
    Calculates tokens spared via n8n compression, caching ROI,
    and cumulative dollar savings vs uncompressed frontier model input.
    """

    # Mid-tier Claude model reference pricing: $3.00 / 1M input tokens
    ANTHROPIC_INPUT_PRICE_PER_M = 3.00

    @classmethod
    def load_stats(cls) -> CumulativeStats:
        config = get_config()
        path = config.get_telemetry_path()
        if not path.exists():
            return CumulativeStats()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CumulativeStats(**data)
        except Exception:
            return CumulativeStats()

    @classmethod
    def save_stats(cls, stats: CumulativeStats):
        config = get_config()
        path = config.get_telemetry_path()
        try:
            path.write_text(json.dumps(asdict(stats), indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def record_command(
        cls,
        intent: str,
        prep_used: bool,
        raw_context_length: int = 0,
        pruned_context_tokens: int = 0,
        duration_ms: float = 0.0,
        is_cache_hit: bool = False,
        circuit_tripped: bool = False,
    ):
        stats = cls.load_stats()
        stats.total_commands += 1
        stats.total_duration_ms += duration_ms

        if is_cache_hit:
            stats.cache_hits += 1
        if circuit_tripped:
            stats.circuit_trips += 1

        if intent == "PREP_AND_EXECUTE":
            stats.prep_invocations += 1
            # Approximate raw uncompressed web doc tokens (~8000 tokens) vs pruned tokens (~1200 tokens)
            estimated_raw_tokens = max(pruned_context_tokens, raw_context_length // 4) if raw_context_length > 0 else 6000
            spared = max(0, estimated_raw_tokens - pruned_context_tokens)
            stats.tokens_compressed += pruned_context_tokens
            stats.context_tokens_spared += spared

            # Dollar savings: spared tokens * Anthropic price
            savings = (spared / 1_000_000) * cls.ANTHROPIC_INPUT_PRICE_PER_M
            stats.dollar_savings_usd += savings
        elif intent == "RESEARCH_ONLY":
            stats.research_only_count += 1
        else:
            stats.execute_only_count += 1

        cls.save_stats(stats)
