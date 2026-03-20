"""Safe text extraction from Kore.ai webhook response message objects.

Kore.ai can return messages as plain strings or structured dicts.
This module normalises both into displayable text while preserving raw structure.
"""
from __future__ import annotations


def extract_text(message: str | dict) -> str:
    """Extract displayable text from a single Kore.ai message object."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return str(message)

    # Direct text fields
    if "val" in message:
        return str(message["val"])
    if "text" in message and isinstance(message["text"], str):
        return message["text"]

    # Nested payload
    payload = message.get("payload")
    if isinstance(payload, dict):
        if "text" in payload:
            return str(payload["text"])

    # Template / rich card — no plain text available
    if message.get("type") == "template":
        return "[template message]"

    # Fallback: stringify the whole thing
    return str(message)


def normalise_messages(messages: list) -> tuple[list[str], list]:
    """Normalise a list of Kore.ai messages.

    Returns:
        texts: list of plain text strings (for LLM classification and display)
        raws: original message objects (for evidence storage)
    """
    texts = [extract_text(m) for m in messages]
    return texts, list(messages)
