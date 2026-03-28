"""Shared sentence-transformers model cache.

Loads paraphrase-multilingual-mpnet-base-v2 once per process and reuses it
across FAQEvaluator and SemanticFieldMapper. Pre-warmed at server startup.
"""

from __future__ import annotations

import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
_model: SentenceTransformer | None = None


def get_shared_model(model_name: str = _MODEL_NAME) -> SentenceTransformer:
    """Return the cached model instance, loading it on first call."""
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: %s (first load)", model_name)
        _model = SentenceTransformer(model_name)
        logger.info("Model loaded and cached.")
    return _model


def reset_model_cache() -> None:
    """Reset the cache — for testing only."""
    global _model
    _model = None
