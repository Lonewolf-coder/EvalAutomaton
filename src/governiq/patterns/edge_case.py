"""Pattern 6 — EDGE_CASE

Inject an invalid value and verify the bot handles it gracefully
with the correct error response.
"""

from __future__ import annotations

import re

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class EdgeCasePattern(PatternExecutor):
    """EDGE_CASE: inject invalid value → verify graceful error handling."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="EDGE_CASE",
            success=False,
        )

        if not self.task.negative_tests:
            result.error = "No negative tests defined for EDGE_CASE task."
            return result

        transcript = self.context.start_transcript(self.task.task_id)
        all_passed = True

        for i, neg_test in enumerate(self.task.negative_tests):
            try:
                await self.webhook.start_session()

                opening = await self.driver.generate_opening(self.task)
                if not opening:
                    opening = self.task.conversation_starter or "Hi"

                bot_response = await self.webhook.send_message(opening)
                self._record_turn(result, "driver", opening)
                self._record_turn(result, "bot", bot_response)

                max_turns = 20
                turn_count = 0
                error_detected = False
                re_entry_offered = False

                import random
                invalid_value = random.choice(neg_test.invalid_value_pool)

                while turn_count < max_turns:
                    turn_count += 1
                    intent = await self.driver.classify_bot_intent(bot_response)

                    if intent == "entity_request":
                        user_msg = await self.driver.generate_entity_injection(
                            "test_value", invalid_value,
                            "invalid test value", bot_response,
                        )
                        bot_response = await self.webhook.send_message(user_msg)
                        self._record_turn(result, "driver", user_msg)
                        self._record_turn(result, "bot", bot_response)

                        # Check if bot responded with expected error pattern
                        if re.search(neg_test.expected_error_pattern, bot_response, re.IGNORECASE):
                            error_detected = True

                        # Check for re-entry prompt
                        re_entry_keywords = {"try again", "re-enter", "another", "again", "retry"}
                        if any(kw in bot_response.lower() for kw in re_entry_keywords):
                            re_entry_offered = True

                        if error_detected:
                            break

                    elif intent == "error":
                        error_detected = True
                        if re.search(neg_test.expected_error_pattern, bot_response, re.IGNORECASE):
                            break
                    else:
                        break

                test_passed = error_detected
                if neg_test.requires_re_entry_prompt and not re_entry_offered:
                    test_passed = False

                if not test_passed:
                    all_passed = False

                result.checks.append(CheckResult(
                    check_id=f"webhook.{self.task.task_id}.edge_case_{i}",
                    task_id=self.task.task_id,
                    pipeline="webhook",
                    label=f"Edge case #{i+1}: invalid value '{invalid_value}'",
                    status=CheckStatus.PASS if test_passed else CheckStatus.FAIL,
                    details=(
                        f"Bot responded with expected error pattern."
                        if error_detected
                        else f"Bot did not respond with expected error pattern."
                    ),
                    score=1.0 if test_passed else 0.0,
                ))

                if neg_test.requires_re_entry_prompt:
                    result.checks.append(CheckResult(
                        check_id=f"webhook.{self.task.task_id}.re_entry_{i}",
                        task_id=self.task.task_id,
                        pipeline="webhook",
                        label=f"Re-entry prompt offered for edge case #{i+1}",
                        status=CheckStatus.PASS if re_entry_offered else CheckStatus.FAIL,
                        details="Re-entry prompt detected." if re_entry_offered
                                else "No re-entry prompt offered.",
                        score=1.0 if re_entry_offered else 0.0,
                    ))

                result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{self.task.task_id}.edge_{i}",
                    task_id=self.task.task_id,
                    title=f"Edge Case #{i+1} — {invalid_value}",
                    content=(
                        f"**Invalid Value:** {invalid_value}\n"
                        f"**Error Detected:** {'Yes' if error_detected else 'No'}\n"
                        f"**Re-entry Offered:** {'Yes' if re_entry_offered else 'No'}"
                    ),
                    color=EvidenceCardColor.GREEN if test_passed else EvidenceCardColor.RED,
                    pipeline="webhook",
                ))

            except Exception as e:
                result.error = str(e)
                all_passed = False

        result.success = all_passed
        return result
