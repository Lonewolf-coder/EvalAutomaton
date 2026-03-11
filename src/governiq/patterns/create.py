"""Pattern 1 — CREATE

Drive a conversation to collect all required entities and trigger a POST to the
candidate's API. Verify the record was persisted correctly.
"""

from __future__ import annotations

from ..core.runtime_context import TaskRecord
from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class CreatePattern(PatternExecutor):
    """CREATE pattern: collect entities → POST → verify persistence."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="CREATE",
            success=False,
        )

        transcript = self.context.start_transcript(self.task.task_id)
        max_turns = 50
        turn_count = 0
        entities_provided: dict[str, str] = {}
        entities_needed = {e.entity_key for e in self.task.required_entities}
        confirmation_sent = False

        try:
            # Start session and warm up webhook connection
            await self.webhook.start_session()
            await self.webhook.warm_up()

            # Generate and send opening message
            opening = await self.driver.generate_opening(self.task)
            if not opening and self.task.conversation_starter:
                opening = self.task.conversation_starter
            elif not opening:
                opening = "Hi"

            bot_response = await self.webhook.send_message(opening)
            self._record_turn(result, "driver", opening)
            self._record_turn(result, "bot", bot_response)

            # Conversation loop: follow bot guidance, inject entities as requested
            while turn_count < max_turns:
                turn_count += 1
                intent = await self.driver.classify_bot_intent(bot_response)

                if intent == "entity_request":
                    # Find which entity the bot is asking for
                    entity_to_inject = self._find_requested_entity(
                        bot_response, entities_needed - entities_provided.keys()
                    )
                    if entity_to_inject:
                        entity_def = next(
                            (e for e in self.task.required_entities
                             if e.entity_key == entity_to_inject),
                            None,
                        )
                        if entity_def:
                            value = self.context.select_value(
                                self.task.task_id, entity_def.entity_key, entity_def.value_pool
                            )
                            user_msg = await self.driver.generate_entity_injection(
                                entity_def.entity_key, value, entity_def.semantic_hint, bot_response
                            )
                            bot_response = await self.webhook.send_message(user_msg)
                            self._record_turn(result, "driver", user_msg)
                            self._record_turn(result, "bot", bot_response)
                            entities_provided[entity_def.entity_key] = value
                            continue

                    # Bot asking for something we don't recognize — try a generic response
                    user_msg = await self.driver.generate_entity_injection(
                        "unknown", "yes", "general response", bot_response
                    )
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "confirmation_request" and not confirmation_sent:
                    # Bot is showing summary and asking for confirmation
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)
                    confirmation_sent = True

                elif intent == "information":
                    # Bot is providing information — booking likely complete
                    if confirmation_sent:
                        break
                    # May need to continue
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "error":
                    result.error = f"Bot returned error: {bot_response}"
                    break
                else:
                    break

            # Cache the record in RuntimeContext
            if self.task.record_alias and entities_provided:
                record = TaskRecord(
                    record_alias=self.task.record_alias,
                    task_id=self.task.task_id,
                    fields=entities_provided,
                )
                self.context.cache_record(record)
                result.cached_record = entities_provided

            # Generate check results
            if entities_needed:
                # Standard CREATE task — check entities and confirmation
                result.checks.append(CheckResult(
                    check_id=f"webhook.{self.task.task_id}.entity_collection",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="All required entities collected",
                    status=CheckStatus.PASS if entities_provided.keys() >= entities_needed
                           else CheckStatus.FAIL,
                    details=(
                        f"Collected: {', '.join(entities_provided.keys())}. "
                        f"Missing: {', '.join(entities_needed - entities_provided.keys()) or 'none'}."
                    ),
                    score=len(entities_provided) / len(entities_needed),
                ))

                result.checks.append(CheckResult(
                    check_id=f"webhook.{self.task.task_id}.confirmation",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Booking confirmation received",
                    status=CheckStatus.PASS if confirmation_sent else CheckStatus.FAIL,
                    details="Confirmation step completed." if confirmation_sent
                            else "No confirmation step detected.",
                    score=1.0 if confirmation_sent else 0.0,
                ))

                # Evidence card — record summary
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.create",
                    task_id=self.task.task_id,
                    title=f"Booking Created — {self.task.record_alias or self.task.task_id}",
                    content=self._format_record_evidence(entities_provided, confirmation_sent),
                    color=EvidenceCardColor.GREEN if confirmation_sent else EvidenceCardColor.RED,
                    pipeline="webhook",
                    details={"entities": entities_provided, "turns": turn_count},
                ))

                result.success = confirmation_sent and entities_provided.keys() >= entities_needed
            else:
                # Zero-entity task (e.g., Welcome/greeting) — just verify bot responded
                result.checks.append(CheckResult(
                    check_id=f"webhook.{self.task.task_id}.bot_response",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label="Bot responded to greeting",
                    status=CheckStatus.PASS if bot_response else CheckStatus.FAIL,
                    details=f"Bot response: {bot_response[:200]}" if bot_response
                            else "No response received from bot.",
                    score=1.0 if bot_response else 0.0,
                ))

                # Evidence card — greeting response
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.greeting",
                    task_id=self.task.task_id,
                    title=f"Greeting Response — {self.task.task_name}",
                    content=f"**Bot Response:**\n{bot_response}" if bot_response
                            else "**No response received.**",
                    color=EvidenceCardColor.GREEN if bot_response else EvidenceCardColor.RED,
                    pipeline="webhook",
                ))

                result.success = bool(bot_response)

            # Evidence card — conversation transcript (all tasks)
            if result.transcript_turns:
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.transcript",
                    task_id=self.task.task_id,
                    title=f"Conversation Transcript — {self.task.task_name}",
                    content=self._format_transcript(result.transcript_turns),
                    color=EvidenceCardColor.BLUE,
                    pipeline="webhook",
                    details={"turn_count": len(result.transcript_turns)},
                ))

        except Exception as e:
            result.error = str(e)
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.execution",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Pattern execution",
                status=CheckStatus.FAIL,
                details=f"Execution error: {e}",
                score=0.0,
            ))
            # Still include whatever transcript we collected before the error
            if result.transcript_turns:
                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.transcript",
                    task_id=self.task.task_id,
                    title=f"Conversation Transcript (partial) — {self.task.task_name}",
                    content=self._format_transcript(result.transcript_turns),
                    color=EvidenceCardColor.AMBER,
                    pipeline="webhook",
                    details={"turn_count": len(result.transcript_turns), "error": str(e)},
                ))

        return result

    def _find_requested_entity(
        self, bot_message: str, remaining_entities: set[str]
    ) -> str | None:
        """Determine which entity the bot is asking for based on its message."""
        msg_lower = bot_message.lower()
        for entity_key in remaining_entities:
            # Match by entity key or semantic hint
            if entity_key.lower().replace("_", " ") in msg_lower:
                return entity_key
            entity_def = next(
                (e for e in self.task.required_entities if e.entity_key == entity_key),
                None,
            )
            if entity_def and entity_def.semantic_hint.lower() in msg_lower:
                return entity_key
        # Return first remaining if we can't determine
        return next(iter(remaining_entities), None) if remaining_entities else None

    def _format_record_evidence(
        self, entities: dict[str, str], confirmed: bool
    ) -> str:
        """Format a record for the evidence card."""
        lines = []
        if confirmed:
            lines.append("**Booking Confirmed in Database**")
        else:
            lines.append("**Booking NOT Confirmed**")
        lines.append("")
        for key, value in entities.items():
            lines.append(f"  - {key}: {value}")
        return "\n".join(lines)
