"""Pattern — FORM

Evaluates digital form behaviour triggered by a specific intent.

Checks:
  - Correct form title displayed when the intent is triggered.
  - All required fields present (verified via CBM config).
  - Conditional visibility rules applied correctly (e.g. hide field when user
    selects "I don't know").
  - Field-level validation: invalid inputs rejected, user re-prompted.
  - POST to mock API on submission — success / failure confirmation shown.
  - Agent handoff initiated after form completion.

Executor status: PENDING — form interaction requires UI-level or structured
webhook introspection that is not yet implemented. Checks marked UNTESTABLE
until the form interaction runtime is available.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class FormPattern(PatternExecutor):
    """FORM: trigger a digital form, fill fields, verify conditional visibility, submit."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="FORM",
            success=False,
            error=(
                "FORM pattern requires structured form-interaction support (field filling, "
                "conditional visibility inspection) which is not yet implemented in the "
                "webhook client. Checks marked UNTESTABLE."
            ),
        )

        for check_id, label in [
            ("form_triggered", "Form triggered on correct intent detection"),
            ("form_title_correct", "Form title matches the required title"),
            ("all_required_fields_present", "All required form fields present with correct types and tooltips"),
            ("conditional_visibility", "Conditional visibility rules applied correctly"),
            ("field_validation", "Invalid field inputs rejected with appropriate re-prompt"),
            ("api_post_on_submit", "POST API called on form submission"),
            ("success_failure_confirmation", "Success or failure confirmation message displayed after submission"),
            ("agent_handoff", "Agent handoff initiated after form completion"),
        ]:
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.{check_id}",
                task_id=self.task.task_id,
                pipeline="webhook",
                label=label,
                status=CheckStatus.UNTESTABLE,
                details=(
                    "Requires form-interaction runtime (field filling, visibility inspection) "
                    "— pending implementation."
                ),
                score=0.0,
                weight=1.0,
            ))

        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.form",
            task_id=self.task.task_id,
            title=f"Form Check — {self.task.task_name}",
            content=(
                "**Status:** UNTESTABLE\n"
                "**Reason:** Form interaction runtime not yet available. "
                "All checks held pending implementation."
            ),
            color=EvidenceCardColor.GREY,
            pipeline="webhook",
        ))

        return result
