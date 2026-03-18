"""Pattern 7 — WELCOME

Send an opening greeting, then verify the bot:
  1. Displays a welcome/greeting message containing the required text.
  2. Presents the required menu items (checked by case-insensitive substring match;
     semantic matching deferred to the LLM-as-user phase).

WELCOME is the only pattern that does not collect entities or call any mock API.
It is always task1 in any manifest.
"""

from __future__ import annotations

import re

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class WelcomePattern(PatternExecutor):
    """WELCOME: send opener → verify greeting + menu items in bot response."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="WELCOME",
            success=False,
        )

        self.context.start_transcript(self.task.task_id)

        required_greeting = (self.task.required_greeting_text or "").strip()
        required_items: list[str] = list(self.task.required_menu_items or [])

        greeting_found = False
        items_found: dict[str, bool] = {item: False for item in required_items}
        # Accumulate all bot text across initial turns for a final scan
        all_bot_text: list[str] = []

        try:
            await self.webhook.start_session()
            await self.webhook.warm_up()

            opener = self.task.conversation_starter or "Hi"
            bot_response = await self.webhook.send_message(opener)
            self._record_turn(result, "driver", opener)
            self._record_turn(result, "bot", bot_response)
            all_bot_text.append(bot_response)

            # WELCOME dialogs sometimes need a second turn before showing the menu.
            # Send one follow-up (select the menu / "what can you help me with?")
            # only if the menu items are not yet visible.
            if required_items and not self._check_items(bot_response, required_items):
                intent = await self.driver.classify_bot_intent(bot_response)
                if intent in ("entity_request", "information"):
                    follow_up = "What can you help me with today?"
                    bot_response2 = await self.webhook.send_message(follow_up)
                    self._record_turn(result, "driver", follow_up)
                    self._record_turn(result, "bot", bot_response2)
                    all_bot_text.append(bot_response2)

            # --- Evaluate combined bot text ---
            combined = " ".join(all_bot_text)

            # 1. Greeting check
            if required_greeting:
                greeting_found = required_greeting.lower() in combined.lower()
            else:
                greeting_found = True  # no requirement — consider passed

            # 2. Menu items check (substring, case-insensitive)
            for item in required_items:
                items_found[item] = item.lower() in combined.lower()

        except Exception as e:
            result.error = str(e)

        # --- Build CheckResults ---
        result.checks.append(CheckResult(
            check_id=f"webhook.{self.task.task_id}.greeting",
            task_id=self.task.task_id,
            pipeline="webhook",
            label=f"Greeting message contains '{required_greeting or '(any)'}'",
            status=CheckStatus.PASS if greeting_found else CheckStatus.FAIL,
            details=(
                f"Required greeting text '{required_greeting}' found in bot response."
                if greeting_found
                else f"Required greeting text '{required_greeting}' not found."
            ),
            score=1.0 if greeting_found else 0.0,
        ))

        for item, found in items_found.items():
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.menu.{_slug(item)}",
                task_id=self.task.task_id,
                pipeline="webhook",
                label=f"Menu item present: '{item}'",
                status=CheckStatus.PASS if found else CheckStatus.FAIL,
                details=(
                    f"Menu item '{item}' found in bot response."
                    if found
                    else f"Menu item '{item}' not found in bot response."
                ),
                score=1.0 if found else 0.0,
            ))

        all_items_present = all(items_found.values()) if items_found else True
        result.success = greeting_found and all_items_present

        # --- Evidence card ---
        missing = [k for k, v in items_found.items() if not v]
        status_line = (
            "All checks passed."
            if result.success
            else f"Missing: {', '.join(missing) if missing else ''}"
            + (" | Greeting not found." if not greeting_found else "")
        )
        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.welcome",
            task_id=self.task.task_id,
            title=f"Welcome Check — {self.task.task_name}",
            content=(
                f"**Greeting found:** {'Yes' if greeting_found else 'No'}\n"
                f"**Menu items checked:** {len(items_found)}\n"
                f"**Items found:** {sum(items_found.values())}/{len(items_found)}\n"
                f"**Status:** {status_line}"
            ),
            color=EvidenceCardColor.GREEN if result.success else EvidenceCardColor.AMBER,
            pipeline="webhook",
        ))

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

        return result

    @staticmethod
    def _check_items(text: str, items: list[str]) -> bool:
        """Return True if all items appear as substrings in text (case-insensitive)."""
        lower = text.lower()
        return all(item.lower() in lower for item in items)


def _slug(text: str) -> str:
    """Convert a display string to a safe check_id fragment."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
