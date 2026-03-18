"""LLM Provider Configuration — Configurable LLM backends for conversation testing.

Supports multiple providers:
- Anthropic (Claude models)
- OpenAI (GPT models)
- Azure OpenAI
- Google Gemini
- Mistral AI
- Ollama (local models — no API key needed)
- LM Studio (local models — no API key needed)

Default: Claude Haiku (lite model for cost optimization).
Admin portal can change the provider at runtime.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("data/llm_config.json")


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    OLLAMA = "ollama"
    LM_STUDIO = "lm_studio"


# Provider-specific defaults
PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-haiku-4-5-20251001",
        "models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
        ],
        "api_format": "anthropic",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        "api_format": "openai",
    },
    "azure_openai": {
        "base_url": "",  # User must set: https://{resource}.openai.azure.com/
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "api_format": "openai",
        "extra_headers": {"api-version": "2024-02-01"},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash-lite",
        "models": ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-1.5-pro"],
        "api_format": "openai",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"],
        "api_format": "openai",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "models": ["llama3.2", "llama3.1", "mistral", "phi3", "gemma2", "qwen2.5", "codellama"],
        "api_format": "openai",  # Ollama exposes OpenAI-compatible API at /v1
    },
    "lm_studio": {
        "base_url": "http://localhost:1234/v1",
        "default_model": "loaded-model",
        "models": ["loaded-model"],
        "api_format": "openai",  # LM Studio exposes OpenAI-compatible API
    },
}


@dataclass
class LLMConfig:
    """Active LLM configuration for the evaluation engine."""
    provider: str = "anthropic"
    api_key: str = ""
    model: str = "claude-haiku-4-5-20251001"
    base_url: str = "https://api.anthropic.com/v1"
    api_format: str = "anthropic"  # "openai" or "anthropic"
    temperature: float = 0.3
    max_tokens: int = 256
    extra_headers: dict[str, str] = field(default_factory=dict)

    # Azure-specific
    azure_deployment: str = ""
    azure_api_version: str = "2024-02-01"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMConfig:
        # Only take known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def get_driver_kwargs(self) -> dict[str, Any]:
        """Return kwargs for LLMConversationDriver constructor."""
        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "api_format": self.api_format,
        }
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        return kwargs


def load_llm_config() -> LLMConfig:
    """Load LLM config from disk, or return defaults."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r") as f:
                data = json.load(f)
            return LLMConfig.from_dict(data)
        except Exception as e:
            logger.warning("Failed to load LLM config: %s", e)
    return LLMConfig()


def save_llm_config(config: LLMConfig) -> None:
    """Persist LLM config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(config.to_dict(), f, indent=2)
    logger.info("LLM config saved to %s", CONFIG_PATH)


def get_provider_info() -> list[dict[str, Any]]:
    """Return info about all supported providers for the admin UI."""
    results = []
    for provider_id, defaults in PROVIDER_DEFAULTS.items():
        results.append({
            "id": provider_id,
            "name": provider_id.replace("_", " ").title(),
            "base_url": defaults["base_url"],
            "default_model": defaults["default_model"],
            "models": defaults["models"],
            "api_format": defaults["api_format"],
        })
    return results
