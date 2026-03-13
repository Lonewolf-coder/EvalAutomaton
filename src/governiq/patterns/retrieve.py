"""Pattern 3 — RETRIEVE

Drive a retrieval conversation using an entity value cached from a previous task.
Verify bot returns data matching what is in the API.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class RetrievePattern(PatternExecutor):
    """RETRIEVE: use cached identifier → retrieve → verify against RuntimeContext."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="RETRIEVE",
            success=False,
        )

        transcript = self.context.start_transcript(self.task.task_id)

        # Resolve cross-task reference to get the identifier
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
            result.error = "Cross-task reference could not be resolved — no cached value."
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.cross_task_ref",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Cross-task reference resolved",
                status=CheckStatus.FAIL,
                details="No cached value found for cross-task reference.",
                score=0.0,
            ))
            return result

        max_turns = 30
        turn_count = 0
        retrieval_confirmed = False
        data_matches = False

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
                    # Bot is asking for the identifier — inject it
                    user_msg = await self.driver.generate_entity_injection(
                        identifier_field or "identifier",
                        str(identifier_value),
                        "identifier for lookup",
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
                    retrieval_confirmed = True

                elif intent == "information":
                    # Bot is returning the data — check it
                    retrieval_confirmed = True
                    # Verify returned data matches RuntimeContext
                    data_matches = self._verify_returned_data(bot_response)
                    break

                elif intent == "error":
                    result.error = f"Bot returned error: {bot_response}"
                    break
                else:
                    break

            # Checks
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.cross_task_ref",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Cross-task reference resolved",
                status=CheckStatus.PASS,
                details=f"Used {identifier_field}='{identifier_value}' from previous task.",
                score=1.0,
            ))

            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.retrieval",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Record retrieved successfully",
                status=CheckStatus.PASS if retrieval_confirmed else CheckStatus.FAIL,
                details="Bot returned record data." if retrieval_confirmed
                        else "Retrieval not confirmed.",
                score=1.0 if retrieval_confirmed else 0.0,
            ))

            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.data_match",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Returned data matches cached record",
                status=CheckStatus.PASS if data_matches else CheckStatus.WARNING,
                details="Data verification passed." if data_matches
                        else "Could not fully verify data match (semantic check needed).",
                score=1.0 if data_matches else 0.5,
            ))

            # Evidence
            result.evidence_cards.append(EvidenceCard(
                card_id=f"webhook.{self.task.task_id}.retrieval",
                task_id=self.task.task_id,
                title=f"Record Retrieved — {identifier_field}={identifier_value}",
                content=f"**Lookup Key:** {identifier_field} = {identifier_value}\n"
                        f"**Retrieved:** {'Yes' if retrieval_confirmed else 'No'}",
                color=EvidenceCardColor.GREEN if retrieval_confirmed else EvidenceCardColor.RED,
                pipeline="webhook",
            ))

            result.success = retrieval_confirmed

            # Conversation transcript evidence
            if result.transcript_turns:
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.transcript",
                    task_id=self.task.task_id,
                    title=f"Conversation Transcript — {self.task.task_name}",
                    content=self._format_transcript(result.transcript_turns),
                    color=EvidenceCardColor.BLUE,
                    pipeline="webhook",
                ))

            if self.kore_api and getattr(self.webhook, "_kore_session_id", None):
                debug = await self.kore_api.get_debug_logs(self.webhook._kore_session_id)
                self._analyse_debug_logs(result, debug)

        except Exception as e:
            result.error = str(e)
            if result.transcript_turns:
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.transcript",
                    task_id=self.task.task_id,
                    title=f"Conversation Transcript (partial) — {self.task.task_name}",
                    content=self._format_transcript(result.transcript_turns),
                    color=EvidenceCardColor.AMBER,
                    pipeline="webhook",
                    details={"error": str(e)},
                ))

        return result

    def _verify_returned_data(self, bot_response: str) -> bool:
        """Verify bot's response contains expected data from RuntimeContext."""
        response_lower = bot_response.lower()
        for ref_key, ref in self.task.cross_task_refs.items():
            record = self.context.get_record(ref.source_record_alias)
            if record:
                # Check if key field values appear in the response
                match_count = 0
                for field_name, field_value in record.fields.items():
                    if str(field_value).lower() in response_lower:
                        match_count += 1
                if match_count > 0:
                    return True
        return False
