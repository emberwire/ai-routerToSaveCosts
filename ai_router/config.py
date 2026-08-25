import json
import os
import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """
    Tiered Configuration for AI-Routed CLI Agent.
    Priority: CLI Flags > Environment Variables / .env > Project Config > User Config (~/.ai_router/config.json) > Org Config (/etc/ai-router/config.json).
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Intent & Model Classifier Settings
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_temperature: float = Field(default=0.0, alias="GEMINI_TEMPERATURE")
    gemini_thinking_budget: int = Field(default=0, alias="GEMINI_THINKING_BUDGET")

    # Research / n8n Pipeline Settings
    n8n_webhook_url: Optional[str] = Field(default="http://localhost:5678/webhook/ai-prep", alias="N8N_WEBHOOK_URL")
    n8n_timeout_seconds: float = Field(default=3.0, alias="N8N_TIMEOUT_SECONDS")
    n8n_max_tokens: int = Field(default=1500, alias="N8N_MAX_TOKENS")
    enable_n8n_prep: bool = Field(default=True, alias="ENABLE_N8N_PREP")
    enable_local_scraper_fallback: bool = Field(default=True, alias="ENABLE_LOCAL_SCRAPER_FALLBACK")

    # Pluggable Execution Engine Settings (Defaults to Opus with Effort 5 Extra)
    default_engine: Literal["claude", "gemini", "codex", "auto"] = Field(default="claude", alias="DEFAULT_ENGINE")
    claude_binary_path: Optional[str] = Field(default="/opt/homebrew/bin/claude", alias="CLAUDE_BINARY_PATH")
    claude_model: str = Field(default="claude-opus-5", alias="CLAUDE_MODEL")
    claude_default_effort: int = Field(default=5, alias="CLAUDE_DEFAULT_EFFORT") # Effort 5 Extra
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    codex_model: str = Field(default="o3-mini", alias="CODEX_MODEL")
    gemini_exec_model: str = Field(default="gemini-2.5-pro", alias="GEMINI_EXEC_MODEL")

    # Cloudflare AI Gateway Settings
    cf_account_id: Optional[str] = Field(default=None, alias="CF_ACCOUNT_ID")
    cf_gateway_id: Optional[str] = Field(default=None, alias="CF_GATEWAY_ID")
    cf_api_token: Optional[str] = Field(default=None, alias="CF_API_TOKEN")
    cf_use_unified_billing: bool = Field(default=False, alias="CF_USE_UNIFIED_BILLING")
    cf_cache_ttl: Optional[int] = Field(default=3600, alias="CF_CACHE_TTL")
    enable_cf_gateway: bool = Field(default=False, alias="ENABLE_CF_GATEWAY")

    # CSO Security & Privacy Guardrails
    enable_dlp_scanner: bool = Field(default=True, alias="ENABLE_DLP_SCANNER")
    enable_prompt_injection_quarantine: bool = Field(default=True, alias="ENABLE_PROMPT_INJECTION_QUARANTINE")
    enable_audit_logging: bool = Field(default=True, alias="ENABLE_AUDIT_LOGGING")
    offline_mode: bool = Field(default=False, alias="OFFLINE_MODE")

    # Storage Paths
    user_config_dir: Path = Field(default_factory=lambda: Path.home() / ".ai_router")
    local_cache_dir: Path = Field(default_factory=lambda: Path(".ai_router"))

    def _ensure_dir(self, directory: Path) -> Path:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return directory
        except (PermissionError, OSError):
            local_fallback = Path(".ai_router")
            local_fallback.mkdir(parents=True, exist_ok=True)
            return local_fallback

    def get_audit_log_path(self) -> Path:
        target_dir = self._ensure_dir(self.user_config_dir)
        return target_dir / "audit.log"

    def get_telemetry_path(self) -> Path:
        target_dir = self._ensure_dir(self.user_config_dir)
        return target_dir / "telemetry.json"

    def get_session_cache_path(self) -> Path:
        target_dir = self._ensure_dir(self.local_cache_dir)
        return target_dir / "last_context.md"

    @classmethod
    def load_hierarchical(cls) -> "AppConfig":
        data = {}
        org_path = Path("/etc/ai-router/config.json")
        if org_path.exists():
            try: data.update(json.loads(org_path.read_text()))
            except Exception: pass

        user_path = Path.home() / ".ai_router" / "config.json"
        if user_path.exists():
            try: data.update(json.loads(user_path.read_text()))
            except Exception: pass

        project_path = Path(".ai-router.json")
        if project_path.exists():
            try: data.update(json.loads(project_path.read_text()))
            except Exception: pass

        return cls(**data)


_config_var: "contextvars.ContextVar[Optional[AppConfig]]" = contextvars.ContextVar(
    "ai_router_config", default=None
)


def get_config() -> AppConfig:
    cfg = _config_var.get()
    if cfg is None:
        cfg = AppConfig.load_hierarchical()
        _config_var.set(cfg)
    return cfg


def set_config(config: AppConfig):
    _config_var.set(config)


@contextmanager
def config_scope(cfg: AppConfig) -> Iterator[AppConfig]:
    """
    Temporarily scopes `get_config()`/`set_config()` to `cfg` for the duration of the
    `with` block, restoring whatever was previously in effect on exit. Lets a facade
    caller (e.g. `AIRouter.route()`) inject a config for one call without permanently
    mutating the ambient process-wide config, and is safe under threads/async.
    """
    token = _config_var.set(cfg)
    try:
        yield cfg
    finally:
        _config_var.reset(token)
