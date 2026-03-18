"""Pattern — CBM_ONLY

For tasks that are evaluated entirely through CBM (Configuration-Based Metrics)
inspection — no live webhook conversation is needed.

Examples:
  - Custom dashboard widget configuration
  - PII redaction settings and masking format
  - Channel publishing configuration

The executor does not initiate a conversation. Instead it returns UNTESTABLE
checks for webhook pipeline items, with the expectation that the CBM pipeline
runs the actual checks against the exported bot configuration.

Executor status: FUNCTIONAL — this executor is intentionally minimal.
All scoring comes from the CBM pipeline, not from a live conversation.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class CbmOnlyPattern(PatternExecutor):
    """CBM_ONLY: no conversation — all checks come from the CBM configuration pipeline."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="CBM_ONLY",
            # CBM_ONLY tasks succeed if the CBM pipeline passes them.
            # The webhook result is always success=True with zero webhook checks,
            # so scoring is driven entirely by cbm_score via the scoring engine.
            success=True,
        )

        result.checks.append(CheckResult(
            check_id=f"webhook.{self.task.task_id}.cbm_only_marker",
            task_id=self.task.task_id,
            pipeline="webhook",
            label="Task evaluated via CBM inspection only — no live conversation required",
            status=CheckStatus.INFO,
            details=(
                "This task is evaluated by inspecting the exported bot configuration (CBM). "
                "No webhook conversation is initiated. Scores come from cbm_checks only."
            ),
            score=1.0,
            weight=0.0,  # zero weight — does not contribute to task score
        ))

        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.cbm_only",
            task_id=self.task.task_id,
            title=f"CBM-Only Task — {self.task.task_name}",
            content=(
                "**Evaluation mode:** CBM configuration inspection only\n"
                "**No conversation conducted** — this task is verified against the "
                "exported bot configuration rather than through live bot interaction."
            ),
            color=EvidenceCardColor.BLUE,
            pipeline="webhook",
        ))

        return result
