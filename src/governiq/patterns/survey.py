"""Pattern — SURVEY

Evaluates NPS / feedback survey behaviour triggered at the end of specific dialogs.

Checks:
  - Survey triggers automatically after the configured trigger dialogs complete.
  - Survey follows the correct flow: scale question → optional text → closing message.
  - Collected feedback appears in the bot's Feedback Dashboard (CBM verification).
  - Feedback is downloadable as a report (CBM verification).

The executor identifies the trigger dialogs from `survey_config.trigger_dialogs` in
the task definition, completes those dialogs via webhook, then checks whether the
survey is launched immediately after.

Executor status: PENDING — requires multi-dialog sequencing in the agentic runtime
and post-dialog state inspection. Checks marked UNTESTABLE until available.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class SurveyPattern(PatternExecutor):
    """SURVEY: complete trigger dialogs and verify NPS survey fires correctly."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="SURVEY",
            success=False,
            error=(
                "SURVEY pattern requires multi-dialog sequencing and post-dialog state "
                "inspection in the agentic runtime. Executor is pending — checks marked "
                "UNTESTABLE."
            ),
        )

        for check_id, label in [
            ("survey_triggers_after_dialog", "Survey triggers automatically after configured trigger dialog completes"),
            ("scale_question_asked", "Bot asks NPS scale question (0–10)"),
            ("optional_text_field_offered", "Optional feedback text field offered after scale response"),
            ("closing_message_correct", "Closing thank-you message matches required text"),
            ("feedback_in_dashboard", "Collected feedback appears in Feedback Dashboard (CBM)"),
            ("feedback_downloadable", "Feedback report is downloadable from dashboard (CBM)"),
        ]:
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.{check_id}",
                task_id=self.task.task_id,
                pipeline="webhook",
                label=label,
                status=CheckStatus.UNTESTABLE,
                details=(
                    "Requires multi-dialog sequencing and agentic runtime — pending implementation."
                ),
                score=0.0,
                weight=1.0,
            ))

        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.survey",
            task_id=self.task.task_id,
            title=f"Survey Check — {self.task.task_name}",
            content=(
                "**Status:** UNTESTABLE\n"
                "**Reason:** Multi-dialog sequencing and post-dialog state inspection "
                "required — pending agentic runtime implementation."
            ),
            color=EvidenceCardColor.GREY,
            pipeline="webhook",
        ))

        return result
