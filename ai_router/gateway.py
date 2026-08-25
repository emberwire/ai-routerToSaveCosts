import re
import json
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from ai_router.config import get_config


@dataclass
class GatewayMetadata:
    cache_status: Optional[str]  # "HIT", "MISS", "BYPASS"
    request_id: Optional[str]
    latency_ms: Optional[float]
    estimated_cost: Optional[float]
    model_routed: Optional[str]


class CloudflareAIGateway:
    """
    Cloudflare AI Gateway Proxy Layer:
    1. Endpoint constructor for individual providers (anthropic, openai, google-ai-studio, workers-ai, groq).
    2. Universal Endpoint constructor for cross-provider fallbacks.
    3. Prompt payload normalizer to maximize exact-match edge cache hits.
    4. Response header inspector (cf-aig-*).
    """

    BASE_GATEWAY_URL = "https://gateway.ai.cloudflare.com/v1"

    @classmethod
    def get_provider_endpoint(cls, provider: str) -> Optional[str]:
        config = get_config()
        if not config.cf_account_id or not config.cf_gateway_id:
            return None

        # Standard Cloudflare AI Gateway provider mappings
        provider_map = {
            "claude": "anthropic",
            "anthropic": "anthropic",
            "codex": "openai",
            "openai": "openai",
            "gemini": "google-ai-studio",
            "google": "google-ai-studio",
            "groq": "groq",
            "workers-ai": "workers-ai",
        }

        mapped = provider_map.get(provider.lower(), provider.lower())
        return f"{cls.BASE_GATEWAY_URL}/{config.cf_account_id}/{config.cf_gateway_id}/{mapped}"

    @classmethod
    def get_universal_endpoint(cls) -> Optional[str]:
        config = get_config()
        if not config.cf_account_id or not config.cf_gateway_id:
            return None
        return f"{cls.BASE_GATEWAY_URL}/{config.cf_account_id}/{config.cf_gateway_id}"

    @classmethod
    def get_gateway_headers(cls, custom_ttl: Optional[int] = None, skip_cache: bool = False) -> Dict[str, str]:
        config = get_config()
        headers = {}

        if config.cf_api_token:
            headers["cf-aig-authorization"] = f"Bearer {config.cf_api_token}"

        ttl = custom_ttl or config.cf_cache_ttl
        if ttl:
            headers["cf-aig-cache-ttl"] = str(ttl)

        if skip_cache:
            headers["cf-aig-skip-cache"] = "true"

        return headers

    @classmethod
    def normalize_prompt_for_cache(cls, prompt_text: str) -> str:
        """
        Normalizes prompt whitespace and structure to ensure consistent edge cache keys.
        """
        # Trim leading/trailing whitespace
        normalized = prompt_text.strip()
        # Normalize carriage returns
        normalized = normalized.replace("\r\n", "\n")
        # Collapse multiple blank lines to double newline
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    @classmethod
    def parse_response_headers(cls, headers: Dict[str, str]) -> GatewayMetadata:
        # Standard Cloudflare AI Gateway response headers
        cache_status = headers.get("cf-aig-cache-status") or headers.get("cf-cache-status")
        req_id = headers.get("cf-aig-request-id") or headers.get("cf-ray")
        latency = float(headers["cf-aig-latency"]) if "cf-aig-latency" in headers else None
        cost = float(headers["cf-aig-cost"]) if "cf-aig-cost" in headers else None
        model = headers.get("cf-aig-model")

        return GatewayMetadata(
            cache_status=cache_status,
            request_id=req_id,
            latency_ms=latency,
            estimated_cost=cost,
            model_routed=model,
        )
