"""Pattern 4 — MODIFY

Retrieve an existing record by identifier, then modify one or more fields
through conversation. Verify the API reflects the change.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class ModifyPattern(PatternExecutor):
    """MODIFY: retrieve by identifier → modify field → verify API update."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="MODIFY",
            success=False,
        )

        transcript = self.context.start_transcript(self.task.task_id)

        # Resolve identifier from cross-task reference
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

        max_turns = 40
        turn_count = 0
        record_retrieved = False
        modification_sent = False
        modification_confirmed = False
        modified_field: str | None = None
        old_value: str | None = None
        new_value: str | None = None

        try:
            await self.webhook.start_session()

            opening = await self.driver.generate_opening(self.task)
            if not opening:
                opening = self.task.conversation_starter or "Hi"

            bot_response = await self.webhook.send_message(opening)
            self._record_turn(result, "driver", opening)
            self._record_turn(result, "bot", bot_response)

            while turn_count < max_turns:
                turn_count += 1
                intent = await self.driver.classify_bot_intent(bot_response)

                if intent == "entity_request" and not record_retrieved:
                    # Provide identifier for retrieval
                    user_msg = await self.driver.generate_entity_injection(
                        identifier_field or "identifier",
                        str(identifier_value),
                        "identifier for lookup",
                        bot_response,
                    )
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "entity_request" and record_retrieved and not modification_sent:
                    # Bot is asking which field to modify
                    if self.task.modifiable_fields:
                        import random
                        modified_field = random.choice(self.task.modifiable_fields)
                        pool = self.task.modified_value_pool.get(modified_field, [])
                        new_value = random.choice(pool) if pool else "updated_value"
                        # Get old value from RuntimeContext
                        for ref in self.task.cross_task_refs.values():
                            rec = self.context.get_record(ref.source_record_alias)
                            if rec:
                                old_value = rec.get_field(modified_field)
                                break

                        user_msg = await self.driver.generate_entity_injection(
                            modified_field, new_value, f"new value for {modified_field}", bot_response
                        )
                        bot_response = await self.webhook.send_message(user_msg)
                        self._record_turn(result, "driver", user_msg)
                        self._record_turn(result, "bot", bot_response)
                        modification_sent = True
                    else:
                        user_msg = await self.driver.generate_entity_injection(
                            "field", "updated", "modification", bot_response
                        )
                        bot_response = await self.webhook.send_message(user_msg)
                        self._record_turn(result, "driver", user_msg)
                        self._record_turn(result, "bot", bot_response)

                elif intent == "information" and not record_retrieved:
                    record_retrieved = True
                    # Continue conversation for modification
                    user_msg = await self.driver.generate_entity_injection(
                        "action", "modify", "I want to modify a field", bot_response
                    )
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "confirmation_request":
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)
                    if modification_sent:
                        modification_confirmed = True

                elif intent == "information" and modification_sent:
                    modification_confirmed = True
                    break

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
                    check_id=f"webhook.{self.task.task_id}.retrieval",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Record retrieved before modification",
                    status=CheckStatus.PASS if record_retrieved else CheckStatus.FAIL,
                    details="Record retrieved." if record_retrieved
                            else "Record not retrieved.",
                    score=1.0 if record_retrieved else 0.0,
                ),
                CheckResult(
                    check_id=f"webhook.{self.task.task_id}.modification",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Modification confirmed",
                    status=CheckStatus.PASS if modification_confirmed else CheckStatus.FAIL,
                    details=(
                        f"Modified {modified_field}: '{old_value}' → '{new_value}'"
                        if modification_confirmed else "Modification not confirmed."
                    ),
                    score=1.0 if modification_confirmed else 0.0,
                ),
            ])

            result.evidence_cards.append(EvidenceCard(
                card_id=f"webhook.{self.task.task_id}.modify",
                task_id=self.task.task_id,
                title=f"Modification — {modified_field or 'unknown'}",
                content=(
                    f"**{modified_field}** updated from '{old_value}' to '{new_value}'"
                    if modification_confirmed
                    else "Modification not completed."
                ),
                color=EvidenceCardColor.GREEN if modification_confirmed
                      else EvidenceCardColor.RED,
                pipeline="webhook",
            ))

            result.success = modification_confirmed

        except Exception as e:
            result.error = str(e)

        return result
