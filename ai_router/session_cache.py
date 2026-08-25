import time
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass
from ai_router.config import get_config


@dataclass
class CachedSessionContext:
    context: str
    source_url: Optional[str]
    timestamp: float
    age_seconds: float
    is_valid: bool


class SessionCache:
    """
    Multi-Turn Session Cache Manager.
    Stores and retrieves the most recent research context in `.ai_router/last_context.md`
    to prevent redundant n8n re-scraping during sequential prompt iterations.
    """

    MAX_CACHE_AGE_SECONDS = 600.0  # 10 minutes cache validity

    @classmethod
    def save_context(cls, context: str, source_url: Optional[str] = None):
        if not context:
            return

        config = get_config()
        cache_path = config.get_session_cache_path()

        header = f"<!-- AI_ROUTER_SESSION_CACHE timestamp={time.time()} source={source_url or 'n8n'} -->\n"
        content = header + context

        try:
            cache_path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def get_latest_context(cls) -> Optional[CachedSessionContext]:
        config = get_config()
        cache_path = config.get_session_cache_path()

        if not cache_path.exists():
            return None

        try:
            raw = cache_path.read_text(encoding="utf-8")
            if not raw:
                return None

            lines = raw.splitlines()
            ts = 0.0
            source_url = None

            if lines and lines[0].startswith("<!-- AI_ROUTER_SESSION_CACHE"):
                header_line = lines[0]
                import re
                ts_match = re.search(r"timestamp=([0-9.]+)", header_line)
                if ts_match:
                    ts = float(ts_match.group(1))
                src_match = re.search(r"source=([^\s]+)", header_line)
                if src_match:
                    source_url = src_match.group(1)
                context_body = "\n".join(lines[1:]).strip()
            else:
                context_body = raw.strip()
                ts = cache_path.stat().st_mtime

            age = time.time() - ts
            is_valid = age <= cls.MAX_CACHE_AGE_SECONDS

            return CachedSessionContext(
                context=context_body,
                source_url=source_url,
                timestamp=ts,
                age_seconds=age,
                is_valid=is_valid,
            )
        except Exception:
            return None

    @classmethod
    def clear_cache(cls):
        config = get_config()
        cache_path = config.get_session_cache_path()
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception:
                pass
