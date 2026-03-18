"""Pattern — LANGUAGE

Evaluates multi-language configuration and runtime switching.

Checks:
  - Configured language(s) present in the bot's CBM language settings.
  - Bot responds in the target language when the user writes in that language.
  - Seamless mid-conversation language switch — bot follows the user's language change.

Language switching is tested by sending a message in the target language after
a portion of the conversation has already happened in English, then verifying
the bot's next response is also in the target language.

Executor status: PENDING — language detection requires an LLM judge or a language
detection library (e.g. langdetect) in the runtime environment. Checks are marked
UNTESTABLE until the dependency is available.
"""

from __future__ import annotations

from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor
from .base import PatternExecutor, PatternResult


class LanguagePattern(PatternExecutor):
    """LANGUAGE: verify multi-language configuration and runtime language switching."""

    async def execute(self) -> PatternResult:
        result = PatternResult(
            task_id=self.task.task_id,
            pattern="LANGUAGE",
            success=False,
            error=(
                "LANGUAGE pattern requires a language-detection library and agentic "
                "runtime to conduct language-switch conversations. Executor is pending "
                "— checks marked UNTESTABLE."
            ),
        )

        for check_id, label in [
            ("language_configured_in_cbm", "Target language configured in bot CBM settings"),
            ("bot_responds_in_target_language", "Bot responds in target language when prompted"),
            ("language_switch_seamless", "Bot follows mid-conversation language switch without re-prompt"),
            ("all_dialogs_translated", "All dialogs and responses available in target language"),
        ]:
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.{check_id}",
                task_id=self.task.task_id,
                pipeline="webhook",
                label=label,
                status=CheckStatus.UNTESTABLE,
                details=(
                    "Requires language-detection library and agentic LLM-as-user runtime "
                    "— pending environment setup."
                ),
                score=0.0,
                weight=1.0,
            ))

        result.evidence_cards.append(EvidenceCard(
            card_id=f"webhook.{self.task.task_id}.language",
            task_id=self.task.task_id,
            title=f"Language Check — {self.task.task_name}",
            content=(
                "**Status:** UNTESTABLE\n"
                "**Reason:** Language-detection capability and agentic runtime required. "
                "All checks held pending environment setup."
            ),
            color=EvidenceCardColor.GREY,
            pipeline="webhook",
        ))

        return result
