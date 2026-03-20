"""Health check helpers — shared between API and Admin routes."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


def check_ai_model(config=None, url: str = "", api_key: str = "") -> dict:
    """Probe the configured LLM provider. Returns dict with status/message/detail.

    Args:
        config: Optional pre-loaded LLMConfig. Loaded from disk when omitted.
        url:    Override the base_url from config (used by the live test-ai endpoint).
        api_key: Override the api_key from config (used by the live test-ai endpoint).
    """
    from .llm_config import load_llm_config  # local import to avoid circular

    if config is None:
        config = load_llm_config()

    probe_url = url or config.base_url
    if not probe_url:
        return {
            "status": "failing",
            "message": "No AI provider configured. Go to Settings to connect an AI model.",
            "detail": "base_url is empty",
        }

    models_url = probe_url.rstrip("/") + "/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        r = httpx.get(models_url, headers=headers, timeout=4.0)
        if r.status_code == 401:
            return {
                "status": "failing",
                "message": "API key invalid or unauthorized. Check your key in Settings.",
                "detail": "HTTP 401",
            }
        if r.status_code < 500:
            return {
                "status": "ok",
                "message": "AI model is connected and ready.",
                "detail": f"HTTP {r.status_code}",
            }
        return {
            "status": "failing",
            "message": "AI model returned an error. Check that the model is loaded.",
            "detail": f"HTTP {r.status_code}",
        }
    except httpx.ConnectError:
        return {
            "status": "failing",
            "message": "AI model is not running. Start LM Studio (or your AI provider) and load a model.",
            "detail": "Connection refused",
        }
    except Exception as exc:
        return {
            "status": "failing",
            "message": "Could not reach the AI model. Check your connection settings.",
            "detail": str(exc)[:120],
        }
