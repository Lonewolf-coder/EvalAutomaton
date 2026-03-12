"""Fingerprint — deterministic SHA-256 hash of a raw Kore.ai bot export.

Operates ONLY on raw appDefinition.json data — NOT on CBMObject.
This module must never import from governiq.cbm.

Same bot always produces the same hash. Hash covers:
  1. Sorted (normalized_dialog_name, sorted_node_types) pairs per dialog
  2. Sorted normalized service URL paths (host+path, no query/credentials)
  3. Sorted entity key names from dialogComponents
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def normalize_dialog_name(name: str) -> str:
    """Lowercase, strip whitespace, remove trailing digits (e.g. '0001')."""
    return re.sub(r"\s*\d+\s*$", "", name.lower().strip())


def extract_service_urls(export_data: dict[str, Any]) -> list[str]:
    """Extract normalized host+path strings from all service components.

    Operates on raw dialogComponents — no CBM dependency.
    """
    urls: list[str] = []
    for comp in export_data.get("dialogComponents", []):
        ep = comp.get("endPoint")
        if not isinstance(ep, dict):
            continue
        host = ep.get("host", "")
        path = ep.get("path", "")
        if host:
            # Normalize: lowercase, strip leading slash on path for consistency
            normalized = f"{host.lower()}{path.lower()}"
            urls.append(normalized)
    return sorted(set(urls))


def extract_entity_keys(export_data: dict[str, Any]) -> list[str]:
    """Extract entity component names (entity key names) from dialogComponents."""
    keys: list[str] = []
    for comp in export_data.get("dialogComponents", []):
        if comp.get("entityType") is not None:
            name = comp.get("name", "")
            if name:
                keys.append(name.lower())
    return sorted(set(keys))


def compute_fingerprint(export_data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint from a raw bot export.

    Args:
        export_data: Raw appDefinition.json dict

    Returns:
        Hex-encoded SHA-256 string
    """
    # Part 1: dialog structure
    dialog_tuples: list[tuple[str, tuple[str, ...]]] = []
    for dialog in export_data.get("dialogs", []):
        locale_en = dialog.get("localeData", {}).get("en", {})
        raw_name = locale_en.get("name") or dialog.get("lname", "")
        norm_name = normalize_dialog_name(raw_name)
        node_types = tuple(sorted(
            node.get("type", "") for node in dialog.get("nodes", [])
        ))
        dialog_tuples.append((norm_name, node_types))
    dialog_tuples.sort()

    # Part 2: service URLs
    service_urls = extract_service_urls(export_data)

    # Part 3: entity keys
    entity_keys = extract_entity_keys(export_data)

    # Combine into a canonical string and hash
    canonical = json.dumps({
        "dialogs": [(name, list(types)) for name, types in dialog_tuples],
        "service_urls": service_urls,
        "entity_keys": entity_keys,
    }, sort_keys=True)

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
