"""Pattern 2 — CREATE_WITH_AMENDMENT

Same as CREATE but mid-conversation, before confirmation, the driver sends an
amendment utterance changing one entity. Tests the Agent Node's amendment capability.

Booking 2 is NOT a separate independent booking test. It is the same booking flow
as Booking 1, with one specific difference: mid-conversation, before the candidate's
bot asks for confirmation, the driver changes one entity value.
"""

from __future__ import annotations

from ..core.runtime_context import TaskRecord
from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class CreateWithAmendmentPattern(PatternExecutor):
    """CREATE_WITH_AMENDMENT: collect entities → amend one → confirm → verify."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="CREATE_WITH_AMENDMENT",
            success=False,
        )

        transcript = self.context.start_transcript(self.task.task_id)
        amendment_config = self.task.amendment_config
        if not amendment_config:
            result.error = "No amendment_config defined for CREATE_WITH_AMENDMENT task."
            return result

        max_turns = 50
        turn_count = 0
        entities_provided: dict[str, str] = {}
        entities_needed = {e.entity_key for e in self.task.required_entities}
        amendment_sent = False
        original_value: str | None = None
        amended_value: str | None = None
        confirmation_sent = False

        try:
            await self.webhook.start_session()
            await self.webhook.warm_up()

            # Opening
            opening = await self.driver.generate_opening(self.task)
            if not opening and self.task.conversation_starter:
                opening = self.task.conversation_starter
            elif not opening:
                opening = "Hi"

            bot_response = await self.webhook.send_message(opening)
            self._record_turn(result, "driver", opening)
            self._record_turn(result, "bot", bot_response)

            while turn_count < max_turns:
                turn_count += 1
                intent = await self.driver.classify_bot_intent(bot_response)

                if intent == "entity_request":
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
                            # Co-referencing test: provide two entities in one response
                            if self.task.co_reference_test and len(entities_provided) == 1:
                                remaining = entities_needed - entities_provided.keys() - {entity_def.entity_key}
                                if remaining:
                                    second_key = next(iter(remaining))
                                    second_def = next(
                                        (e for e in self.task.required_entities if e.entity_key == second_key),
                                        None,
                                    )
                                    if second_def:
                                        second_val = self.context.select_value(
                                            self.task.task_id, second_key, second_def.value_pool
                                        )
                                        user_msg = await self.driver.generate_entity_injection(
                                            entity_def.entity_key,
                                            f"{value} and my {second_def.semantic_hint} is {second_val}",
                                            entity_def.semantic_hint,
                                            bot_response,
                                        )
                                        entities_provided[second_key] = second_val

                            else:
                                user_msg = await self.driver.generate_entity_injection(
                                    entity_def.entity_key, value, entity_def.semantic_hint, bot_response
                                )

                            bot_response = await self.webhook.send_message(user_msg)
                            self._record_turn(result, "driver", user_msg)
                            self._record_turn(result, "bot", bot_response)
                            entities_provided[entity_def.entity_key] = value
                            continue

                    user_msg = await self.driver.generate_entity_injection(
                        "unknown", "yes", "general response", bot_response
                    )
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "confirmation_request" and not amendment_sent:
                    # BEFORE confirmation: send the amendment
                    import random
                    amended_value = random.choice(amendment_config.amended_value_pool)
                    original_value = entities_provided.get(amendment_config.target_entity)
                    amendment_msg = await self.driver.generate_amendment(
                        amendment_config.amendment_utterance_template, amended_value
                    )
                    bot_response = await self.webhook.send_message(amendment_msg)
                    self._record_turn(result, "driver", amendment_msg)
                    self._record_turn(result, "bot", bot_response)
                    entities_provided[amendment_config.target_entity] = amended_value
                    amendment_sent = True

                elif intent == "confirmation_request" and amendment_sent and not confirmation_sent:
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)
                    confirmation_sent = True

                elif intent == "information":
                    if confirmation_sent:
                        break
                    user_msg = await self.driver.generate_confirmation(bot_response)
                    bot_response = await self.webhook.send_message(user_msg)
                    self._record_turn(result, "driver", user_msg)
                    self._record_turn(result, "bot", bot_response)

                elif intent == "error":
                    result.error = f"Bot returned error: {bot_response}"
                    break
                else:
                    break

            # Cache record with amended value
            if self.task.record_alias and entities_provided:
                record = TaskRecord(
                    record_alias=self.task.record_alias,
                    task_id=self.task.task_id,
                    fields=entities_provided,
                )
                self.context.cache_record(record)
                result.cached_record = entities_provided

            # Checks
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
                score=len(entities_provided) / max(len(entities_needed), 1),
            ))

            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.amendment",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Amendment accepted by Agent Node",
                status=CheckStatus.PASS if amendment_sent else CheckStatus.FAIL,
                details=(
                    f"Amended {amendment_config.target_entity} from "
                    f"'{original_value}' to '{amended_value}'."
                    if amendment_sent
                    else "Amendment was not sent."
                ),
                score=1.0 if amendment_sent else 0.0,
            ))

            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.confirmation",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Booking confirmation after amendment",
                status=CheckStatus.PASS if confirmation_sent else CheckStatus.FAIL,
                details="Confirmation completed after amendment." if confirmation_sent
                        else "No confirmation after amendment.",
                score=1.0 if confirmation_sent else 0.0,
            ))

            # Evidence card
            result.evidence_cards.append(EvidenceCard(
                card_id=f"webhook.{self.task.task_id}.amendment_evidence",
                task_id=self.task.task_id,
                title=(
                    f"Booking Created with Amendment — "
                    f"{self.task.record_alias or self.task.task_id}"
                ),
                content=(
                    f"**Amendment Applied:** {amendment_config.target_entity} "
                    f"changed from '{original_value}' to '{amended_value}'\n\n"
                    + "\n".join(f"  - {k}: {v}" for k, v in entities_provided.items())
                ),
                color=EvidenceCardColor.GREEN if (amendment_sent and confirmation_sent)
                      else EvidenceCardColor.RED,
                pipeline="webhook",
                details={
                    "entities": entities_provided,
                    "amendment_target": amendment_config.target_entity,
                    "original_value": original_value,
                    "amended_value": amended_value,
                },
            ))

            result.success = amendment_sent and confirmation_sent

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

        return result

    def _find_requested_entity(
        self, bot_message: str, remaining_entities: set[str]
    ) -> str | None:
        msg_lower = bot_message.lower()
        for entity_key in remaining_entities:
            if entity_key.lower().replace("_", " ") in msg_lower:
                return entity_key
            entity_def = next(
                (e for e in self.task.required_entities if e.entity_key == entity_key),
                None,
            )
            if entity_def and entity_def.semantic_hint.lower() in msg_lower:
                return entity_key
        return next(iter(remaining_entities), None) if remaining_entities else None
