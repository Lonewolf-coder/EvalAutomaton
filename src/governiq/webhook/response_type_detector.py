"""Response Type Detector — classify Kore.ai webhook data[] responses.

Kore.ai V2 webhook sends structured payloads for buttons, forms, carousels,
and URLs alongside plain text. This module detects the response type so the
correct handler can process it.

Response type hierarchy (first match wins):
  EXTERNAL_URL  — button element with web_url type
  INLINE_FORM   — template_type == "form"
  CAROUSEL      — template_type == "carousel"
  BUTTONS       — template_type == "quick_replies", "buttons", or "button" (without web_url)
  TEXT          — everything else (including unknown template types)
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ResponseType(str, Enum):
    TEXT = "text"
    BUTTONS = "buttons"
    INLINE_FORM = "inline_form"
    CAROUSEL = "carousel"
    EXTERNAL_URL = "external_url"


def detect_response_type(
    messages: list[Any],
) -> tuple[ResponseType, dict[str, Any] | None]:
    """Classify a list of message objects from a single bot turn.

    Returns:
        (ResponseType, payload) where payload is the structured dict for
        non-text types, or None for TEXT.

    Template types take precedence over plain text in the same turn.
    Unknown template_type values fall back to TEXT.
    """
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "template":
            continue

        payload = msg.get("payload", {})
        template_type = payload.get("template_type", "")
        elements = payload.get("elements", [])

        # External URL — button element with web_url type
        if template_type in ("button", "quick_replies", "buttons"):
            for el in elements:
                if isinstance(el, dict) and el.get("type") == "web_url":
                    url = el.get("url", "")
                    if url:
                        return ResponseType.EXTERNAL_URL, {"url": url, "element": el}

        if template_type == "form":
            return ResponseType.INLINE_FORM, payload

        if template_type == "carousel":
            return ResponseType.CAROUSEL, payload

        if template_type in ("quick_replies", "buttons", "button"):
            return ResponseType.BUTTONS, payload

        # Unknown template type — fall through to TEXT
        return ResponseType.TEXT, None

    return ResponseType.TEXT, None
