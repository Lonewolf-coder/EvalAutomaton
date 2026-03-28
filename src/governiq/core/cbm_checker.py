"""CBM Structural Checker — informational checks against the bot's CBM.

All checks in this module are WARN severity. They never block evaluation.
Scoring authority rests entirely with the webhook functional pipeline.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_faq_cbm_coverage(
    faq_tasks: list,
    cbm_faqs: list[dict],
    min_alternatives: int = 2,
    match_threshold: float = 0.85,
) -> list[dict]:
    """Check each faq_task has a matching, fully-configured FAQ node in the bot's CBM.

    Returns a list of defect dicts: [{task_id, check_id, message, severity}]
    All defects are WARN (informational — CBM checks never block evaluation).
    """
    from governiq.webhook.model_cache import get_shared_model
    import numpy as np

    defects = []
    if not cbm_faqs:
        for task in faq_tasks:
            defects.append({
                "task_id": task.task_id,
                "check_id": "cbm.faq.node_missing",
                "message": (
                    f"FAQ task '{task.task_id}': not found — no FAQ nodes configured in bot CBM. "
                    "Configure FAQ responses in the bot platform's knowledge base."
                ),
                "severity": "warn",
            })
        return defects

    model = get_shared_model()

    cbm_questions = [faq.get("question", "") for faq in cbm_faqs]
    cbm_embs = model.encode(cbm_questions, convert_to_numpy=True)
    cbm_norm_embs = [e / (np.linalg.norm(e) + 1e-9) for e in cbm_embs]

    for task in faq_tasks:
        task_emb = model.encode([task.question], convert_to_numpy=True)[0]
        task_emb = task_emb / (np.linalg.norm(task_emb) + 1e-9)

        best_match, best_sim = None, 0.0

        for i, norm_emb in enumerate(cbm_norm_embs):
            sim = float(np.dot(task_emb, norm_emb))
            if sim > best_sim:
                best_sim = sim
                best_match = cbm_faqs[i]

        if best_sim < match_threshold or best_match is None:
            defects.append({
                "task_id": task.task_id,
                "check_id": "cbm.faq.node_missing",
                "message": (
                    f"FAQ task '{task.task_id}' (question: '{task.question}') "
                    f"not found in bot CBM (best similarity: {best_sim:.2f}, "
                    f"threshold: {match_threshold}). "
                    "Add this FAQ to the bot's knowledge base."
                ),
                "severity": "warn",
            })
            continue

        alternatives = best_match.get("alternatives", [])
        if len(alternatives) < min_alternatives:
            defects.append({
                "task_id": task.task_id,
                "check_id": "cbm.faq.insufficient_alternatives",
                "message": (
                    f"FAQ task '{task.task_id}': found {len(alternatives)} alternative question(s), "
                    f"need at least {min_alternatives}. "
                    "Add more alternative phrasings for this FAQ in the bot platform."
                ),
                "severity": "warn",
            })

        answer = best_match.get("answer", "").strip()
        if not answer:
            defects.append({
                "task_id": task.task_id,
                "check_id": "cbm.faq.empty_answer",
                "message": (
                    f"FAQ task '{task.task_id}': matched FAQ node has an empty answer. "
                    "Provide an answer for this FAQ in the bot platform."
                ),
                "severity": "warn",
            })

    return defects
