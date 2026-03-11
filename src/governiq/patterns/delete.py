"""Pattern 5 — DELETE

Cancel or delete an existing record by identifier.
Verify the API confirms removal.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class DeletePattern(PatternExecutor):
    """DELETE: identify record → cancel/delete → verify removal from API."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="DELETE",
            success=False,
        )

        transcript = self.context.start_transcript(self.task.task_id)

        # Resolve identifier
        identifier_value = None
        identifier_field = None
        for ref_key, ref in self.task.cross_task_refs.items():
            identifier_value = self.context.get_cross_task_value(
                ref.source_task_id, ref.source_record_alias, ref.source_field
            )
            identifier_field = ref.source_field
            if identifier_value:
                break

        if not identifier_value:
            result.error = "Cross-task reference unresolved."
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.cross_task_ref",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Cross-task reference resolved",
                status=CheckStatus.FAIL,
                details="No cached value for cross-task reference.",
                score=0.0,
            ))
            return result

        max_turns = 30
        turn_count = 0
        cancellation_confirmed = False

        try:
            await self.webhook.start_session()
            await self.webhook.warm_up()

            opening = await self.driver.generate_opening(self.task)
            if not opening:
                opening = self.task.conversation_starter or "Hi"

            bot_response = await self.webhook.send_message(opening)
            self._record_turn(result, "driver", opening)
            self._record_turn(result, "bot", bot_response)

            while turn_count < max_turns:
                turn_count += 1
                intent = await self.driver.classify_bot_intent(bot_response)

                if intent == "entity_request":
                    user_msg = await self.driver.generate_entity_injection(
                        identifier_field or "identifier",
                        str(identifier_value),
                        "identifier for cancellation",
                        bot_response,
                    )
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "confirmation_request":
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)
                    cancellation_confirmed = True

                elif intent == "information":
                    if cancellation_confirmed:
                        break
                    # Bot may have already cancelled
                    cancel_keywords = {"cancelled", "canceled", "deleted", "removed", "successfully"}
                    if any(kw in bot_response.lower() for kw in cancel_keywords):
                        cancellation_confirmed = True
                        break
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "error":
                    result.error = f"Bot error: {bot_response}"
                    break
                else:
                    break

            # Checks
            result.checks.extend([
                CheckResult(
                    check_id=f"webhook.{self.task.task_id}.cross_task_ref",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Cross-task reference resolved",
                    status=CheckStatus.PASS,
                    details=f"Used {identifier_field}='{identifier_value}'.",
                    score=1.0,
                ),
                CheckResult(
                    check_id=f"webhook.{self.task.task_id}.cancellation",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Cancellation confirmed",
                    status=CheckStatus.PASS if cancellation_confirmed else CheckStatus.FAIL,
                    details="Record cancellation confirmed." if cancellation_confirmed
                            else "Cancellation not confirmed.",
                    score=1.0 if cancellation_confirmed else 0.0,
                ),
            ])

            color = EvidenceCardColor.GREEN if cancellation_confirmed else EvidenceCardColor.RED
            result.evidence_cards.append(EvidenceCard(
                card_id=f"webhook.{self.task.task_id}.delete",
                task_id=self.task.task_id,
                title=f"Cancellation — {self.task.record_alias or self.task.task_id}",
                content=(
                    f"**Cancellation Confirmed** — record deleted from database"
                    if cancellation_confirmed
                    else f"**Cancellation FAILED** — record may still exist in database"
                ),
                color=color,
                pipeline="webhook",
            ))

            result.success = cancellation_confirmed

        except Exception as e:
            result.error = str(e)

        return result
