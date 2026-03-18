"""Pattern — INTERRUPTION

Evaluates global interruption handling: whether the bot can handle an out-of-context
request mid-dialog, respond correctly, and then resume the interrupted task by name.

Two interruption scenarios are expected per task definition:
  1. A query that triggers a mock API call (e.g. weather).
  2. A query that triggers an FAQ answer.

After handling either interruption the bot must say the configured resume phrase
(default: "Resuming your previous task: <dialog_name>").

Executor status: PENDING — requires LLM-as-user architecture to inject interruptions
at a specific turn within an ongoing conversation. Mark checks as UNTESTABLE until
the agentic runtime is available.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class InterruptionPattern(PatternExecutor):
    """INTERRUPTION: inject out-of-context requests mid-dialog, verify recovery."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="INTERRUPTION",
            success=False,
            error=(
                "INTERRUPTION pattern requires agentic LLM-as-user runtime to inject "
                "interruptions at a specific conversational turn. Executor is pending "
                "architecture approval — checks marked UNTESTABLE."
            ),
        )

        for check_id, label in [
            ("global_interruption_configured", "Global interruption rule enabled in bot configuration"),
            ("weather_interrupt_handled", "Bot handles weather query interruption and calls weather API"),
            ("weather_resume_message", "Bot says resume phrase after weather interruption"),
            ("faq_interrupt_handled", "Bot handles FAQ query interruption with correct answer"),
            ("faq_resume_message", "Bot says resume phrase after FAQ interruption"),
        ]:
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.{check_id}",
                task_id=self.task.task_id,
                pipeline="webhook",
                label=label,
                status=CheckStatus.UNTESTABLE,
                details="Requires agentic LLM-as-user runtime — pending architecture review.",
                score=0.0,
                weight=1.0,
            ))

        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.interruption",
            task_id=self.task.task_id,
            title=f"Interruption Check — {self.task.task_name}",
            content=(
                "**Status:** UNTESTABLE\n"
                "**Reason:** Agentic LLM-as-user runtime required to inject mid-dialog "
                "interruptions. All checks held pending architecture approval."
            ),
            color=EvidenceCardColor.GREY,
            pipeline="webhook",
        ))

        return result
