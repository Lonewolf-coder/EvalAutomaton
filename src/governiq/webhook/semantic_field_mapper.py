"""Semantic Field Mapper — maps webhook UI payloads to manifest entity values.

Called by the Webhook Driver after the Response Type Detector identifies a
structured response (buttons, inline form, carousel). The mapper finds the
best match for the persona's entity value within the UI payload, and
returns what to send back to the bot.

No browser required — this operates entirely on the webhook JSON.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MappingResult:
    matched_label: str | None
    strategy: str   # "exact", "contains", "semantic", "fallback"
    confidence: float
    index: int = 0  # position in the list (for click/select payloads)


class SemanticFieldMapper:
    """Maps persona entity values to webhook UI element selections."""

    def __init__(self, similarity_threshold: float = 0.60):
        self._similarity_threshold = similarity_threshold
        self._model = None  # Loaded lazily

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        return self._model

    def _semantic_best_match(
        self, target: str, candidates: list[str]
    ) -> tuple[int, float]:
        """Return (index, similarity) of the best semantic match."""
        import numpy as np
        model = self._get_model()
        all_texts = [target] + candidates
        embeddings = model.encode(all_texts, convert_to_numpy=True)
        target_emb = embeddings[0] / (np.linalg.norm(embeddings[0]) + 1e-9)
        best_idx, best_sim = 0, -1.0
        for i, emb in enumerate(embeddings[1:]):
            norm_emb = emb / (np.linalg.norm(emb) + 1e-9)
            sim = float(np.dot(target_emb, norm_emb))
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        return best_idx, best_sim

    def map_buttons(
        self, buttons: list[dict[str, Any]], target_value: str
    ) -> MappingResult:
        """Find the button label best matching target_value.

        Strategy: exact -> contains -> semantic -> fallback (first button).
        """
        if not buttons:
            raise ValueError("No buttons to map against.")

        labels = [b.get("title", "") for b in buttons]

        # Exact match
        for i, label in enumerate(labels):
            if label.lower() == target_value.lower():
                return MappingResult(matched_label=label, strategy="exact", confidence=1.0, index=i)

        # Contains match
        for i, label in enumerate(labels):
            if target_value.lower() in label.lower() or label.lower() in target_value.lower():
                return MappingResult(matched_label=label, strategy="contains", confidence=0.85, index=i)

        # Semantic match
        best_idx, best_sim = self._semantic_best_match(target_value, labels)
        if best_sim >= self._similarity_threshold:
            return MappingResult(
                matched_label=labels[best_idx],
                strategy="semantic",
                confidence=best_sim,
                index=best_idx,
            )

        # Fallback — return first with low confidence
        logger.warning(
            "Button mapping: no match for '%s' in %s — falling back to first button.",
            target_value, labels,
        )
        return MappingResult(matched_label=labels[0], strategy="fallback", confidence=0.0, index=0)

    def map_form(
        self,
        form_components: list[dict[str, Any]],
        entity_map: dict[str, dict[str, Any]],
    ) -> dict[str, str | None]:
        """Map form component keys to entity values.

        entity_map: { entityKey: {"value": "...", "label_hints": ["..."]} }
        Returns: { componentKey: value or None if unmapped }
        """
        result: dict[str, str | None] = {}
        comp_labels = [c.get("displayName", "") for c in form_components]
        comp_keys = [c.get("key", "") for c in form_components]

        for comp_key, comp_label in zip(comp_keys, comp_labels):
            matched_value = None
            for entity_key, entity_info in entity_map.items():
                hints = entity_info.get("label_hints", [])
                value = entity_info.get("value", "")
                for hint in hints:
                    if hint.lower() == comp_label.lower() or hint.lower() in comp_label.lower():
                        matched_value = value
                        break
                if matched_value is not None:
                    break
            result[comp_key] = matched_value

        return result

    def map_carousel(
        self,
        cards: list[dict[str, Any]],
        target_value: str,
        strategy: str = "semantic",
    ) -> MappingResult:
        """Find the card best matching target_value.

        strategy: "exact" | "contains" | "semantic"
        """
        if not cards:
            raise ValueError("No carousel cards to map against.")

        titles = [c.get("title", "") for c in cards]

        if strategy == "exact":
            for i, title in enumerate(titles):
                if title.lower() == target_value.lower():
                    return MappingResult(matched_label=title, strategy="exact", confidence=1.0, index=i)

        if strategy in ("contains", "exact"):
            for i, title in enumerate(titles):
                if target_value.lower() in title.lower():
                    return MappingResult(matched_label=title, strategy="contains", confidence=0.85, index=i)

        # Semantic (default)
        best_idx, best_sim = self._semantic_best_match(target_value, titles)
        return MappingResult(
            matched_label=titles[best_idx],
            strategy="semantic",
            confidence=best_sim,
            index=best_idx,
        )
