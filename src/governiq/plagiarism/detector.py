"""Plagiarism Detector — compares a bot export against all prior submissions.

Operates ONLY on raw appDefinition.json data and a local fingerprint store.
Never imports from governiq.cbm — independent of the parser.

Risk levels:
  NONE   — fingerprint not seen before
  LOW    — service URLs match another submission but structure differs
  MEDIUM — fingerprint matches (same structure, possibly renamed dialogs)
  HIGH   — fingerprint matches AND service URLs match (strong copy indicator)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .fingerprint import compute_fingerprint, extract_service_urls


class PlagiarismRisk(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PlagiarismReport:
    risk_level: PlagiarismRisk
    current_fingerprint: str
    matching_submission_ids: list[str]
    matching_elements: list[str]        # human-readable: what matched
    same_apis: bool                     # True if service URLs identical to another submission
    fingerprint_similarity: float       # 1.0 = exact match, 0.0 = no match
    message: str                        # human-readable explanation


# ---------------------------------------------------------------------------
# Fingerprint store — persists to {data_dir}/fingerprints/{assessment_type}.json
# ---------------------------------------------------------------------------

def _store_path(assessment_type: str, data_dir: str) -> Path:
    return Path(data_dir) / "fingerprints" / f"{assessment_type}.json"


def _load_store(assessment_type: str, data_dir: str) -> dict[str, Any]:
    path = _store_path(assessment_type, data_dir)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save_to_store(
    submission_id: str,
    fingerprint: str,
    service_urls: list[str],
    assessment_type: str,
    data_dir: str,
) -> None:
    """Persist this submission's fingerprint to the store."""
    path = _store_path(assessment_type, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = _load_store(assessment_type, data_dir)
    store[submission_id] = {
        "fingerprint": fingerprint,
        "service_urls": service_urls,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

def _classify_risk(
    current_fp: str,
    current_urls: list[str],
    store: dict[str, Any],
    current_submission_id: str,
) -> tuple[PlagiarismRisk, list[str], list[str], bool, float]:
    """Return (risk, matching_ids, matching_elements, same_apis, similarity)."""
    fp_matches: list[str] = []
    url_matches: list[str] = []

    for sub_id, entry in store.items():
        if sub_id == current_submission_id:
            continue
        stored_fp = entry.get("fingerprint", "")
        stored_urls = entry.get("service_urls", [])

        if stored_fp == current_fp:
            fp_matches.append(sub_id)
        elif set(current_urls) & set(stored_urls):
            url_matches.append(sub_id)

    # Matching elements description
    matching_elements: list[str] = []
    if fp_matches:
        matching_elements.append(f"Bot structure identical to: {', '.join(fp_matches)}")
    if url_matches:
        matching_elements.append(f"Same API URLs as: {', '.join(url_matches)}")

    same_apis = bool(fp_matches)  # fp match implies URL match too
    similarity = 1.0 if fp_matches else (0.5 if url_matches else 0.0)

    if fp_matches and any(
        set(current_urls) == set(store[sid].get("service_urls", []))
        for sid in fp_matches
        if sid in store
    ):
        risk = PlagiarismRisk.HIGH
        message = (
            f"HIGH RISK: Bot structure and API endpoints are identical to "
            f"submission(s) {', '.join(fp_matches)}. Strong copy indicator."
        )
    elif fp_matches:
        risk = PlagiarismRisk.MEDIUM
        message = (
            f"MEDIUM RISK: Bot structure matches submission(s) {', '.join(fp_matches)}. "
            "Dialog/node layout is the same but API URLs may differ."
        )
    elif url_matches:
        risk = PlagiarismRisk.LOW
        message = (
            f"LOW RISK: API endpoints overlap with submission(s) {', '.join(url_matches)}. "
            "Bot structure is different."
        )
    else:
        risk = PlagiarismRisk.NONE
        message = "No plagiarism indicators found."

    all_matching = list(set(fp_matches + url_matches))
    return risk, all_matching, matching_elements, same_apis, similarity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(
    export_data: dict[str, Any],
    assessment_type: str,
    current_submission_id: str,
    data_dir: str = "./data",
) -> PlagiarismReport:
    """Compare a bot export against all prior submissions for an assessment type.

    Saves the current fingerprint to the store after comparison so future
    submissions can be compared against it.

    Args:
        export_data: Raw appDefinition.json dict
        assessment_type: e.g. "medical", "travel"
        current_submission_id: Unique ID for this submission
        data_dir: Root data directory (default: "./data")

    Returns:
        PlagiarismReport with risk level and evidence
    """
    current_fp = compute_fingerprint(export_data)
    current_urls = extract_service_urls(export_data)

    store = _load_store(assessment_type, data_dir)
    risk, matching_ids, matching_elements, same_apis, similarity = _classify_risk(
        current_fp, current_urls, store, current_submission_id
    )

    # Persist AFTER comparison so self-comparison doesn't occur
    _save_to_store(current_submission_id, current_fp, current_urls, assessment_type, data_dir)

    return PlagiarismReport(
        risk_level=risk,
        current_fingerprint=current_fp,
        matching_submission_ids=matching_ids,
        matching_elements=matching_elements,
        same_apis=same_apis,
        fingerprint_similarity=similarity,
        message=risk.value.upper() + " — " + (matching_elements[0] if matching_elements else "No matches found."),
    )
