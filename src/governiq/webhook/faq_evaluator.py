"""FAQ Evaluator — live webhook FAQ evaluation via semantic similarity.

For each FAQTask in the manifest, sends the configured question to the
candidate's bot in an isolated webhook session, then scores the response
against the expected_answer using a multilingual sentence-transformers model.

Model: paraphrase-multilingual-mpnet-base-v2
  - Handles bot responses in any language
  - Loaded once per FAQEvaluator instance, shared across all FAQ tasks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.manifest import FAQTask
from .model_cache import get_shared_model, _MODEL_NAME

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class FAQEvalResult:
    task_id: str
    similarity: float
    threshold: float
    bot_response: str
    expected_answer: str

    @property
    def passed(self) -> bool:
        return self.similarity >= self.threshold

    def to_evidence_dict(self) -> dict:
        """Return a dict suitable for adding to evidence records."""
        return {
            "faq_task_id": self.task_id,
            "similarity": round(self.similarity, 4),
            "threshold": self.threshold,
            "passed": self.passed,
            "bot_response": self.bot_response,
            "expected_answer": self.expected_answer,
        }


class FAQEvaluator:
    """Runs live FAQ evaluation for all FAQ tasks in the manifest."""

    def __init__(
        self,
        webhook_driver: object,  # KoreWebhookClient — imported at call site to avoid circular
        submission_id: str,
    ):
        self._driver = webhook_driver
        self._submission_id = submission_id

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        """Cosine similarity between two strings using the multilingual model."""
        model = get_shared_model()
        embeddings = model.encode([text_a, text_b], convert_to_numpy=True)
        a = embeddings[0] / (np.linalg.norm(embeddings[0]) + 1e-9)
        b = embeddings[1] / (np.linalg.norm(embeddings[1]) + 1e-9)
        return float(np.dot(a, b))

    async def evaluate_task(self, task: FAQTask) -> FAQEvalResult:
        """Run a single FAQ question and score the response."""
        session_id = f"eval-{self._submission_id}-{task.task_id}"
        logger.info("FAQ evaluation: task=%s session=%s", task.task_id, session_id)
        bot_response = await self._driver.run_faq_turn(
            question=task.question,
            session_id=session_id,
        )
        similarity = self._compute_similarity(bot_response, task.expected_answer)
        logger.info(
            "FAQ %s: similarity=%.3f threshold=%.3f passed=%s",
            task.task_id, similarity, task.similarity_threshold,
            similarity >= task.similarity_threshold,
        )
        return FAQEvalResult(
            task_id=task.task_id,
            similarity=similarity,
            threshold=task.similarity_threshold,
            bot_response=bot_response,
            expected_answer=task.expected_answer,
        )

    async def evaluate_all(self, faq_tasks: list[FAQTask]) -> list[FAQEvalResult]:
        """Evaluate all FAQ tasks sequentially."""
        results = []
        for task in faq_tasks:
            try:
                result = await self.evaluate_task(task)
            except Exception as e:
                logger.error("FAQ task %s failed: %s", task.task_id, e)
                result = FAQEvalResult(
                    task_id=task.task_id,
                    similarity=0.0,
                    threshold=task.similarity_threshold,
                    bot_response=f"[ERROR: {e}]",
                    expected_answer=task.expected_answer,
                )
            results.append(result)
        return results
