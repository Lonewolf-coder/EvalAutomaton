"""Base pattern executor — interface all six patterns implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.manifest import TaskDefinition
from ..core.runtime_context import RuntimeContext
from ..core.scoring import CheckResult, EvidenceCard


@dataclass
class PatternResult:
    """Result of executing a pattern against a live bot."""
    task_id: str
    pattern: str
    success: bool
    checks: list[CheckResult] = field(default_factory=list)
    evidence_cards: list[EvidenceCard] = field(default_factory=list)
    transcript_turns: list[dict[str, str]] = field(default_factory=list)
    cached_record: dict[str, Any] | None = None
    error: str | None = None


class WebhookClient(Protocol):
    """Protocol for sending messages to a bot webhook."""

    async def send_message(self, message: str) -> str:
        """Send a message and return the bot's response."""
        ...

    async def start_session(self) -> None:
        """Start a new conversation session."""
        ...


class ConversationDriver(Protocol):
    """Protocol for the LLM-powered conversation driver."""

    async def generate_opening(self, task: TaskDefinition) -> str:
        """Generate an opening message for the task."""
        ...

    async def generate_entity_injection(
        self, entity_key: str, value: str, semantic_hint: str, bot_message: str
    ) -> str:
        """Generate a natural message that provides an entity value."""
        ...

    async def generate_amendment(self, template: str, amended_value: str) -> str:
        """Generate an amendment utterance."""
        ...

    async def generate_confirmation(self, bot_message: str) -> str:
        """Generate a confirmation response to the bot."""
        ...

    async def classify_bot_intent(self, bot_message: str) -> str:
        """Classify the bot's message into one of four states:
        'entity_request', 'confirmation_request', 'information', 'error'
        """
        ...


class PatternExecutor(ABC):
    """Abstract base for all six engine patterns.

    Each pattern knows how to drive a conversation for its purpose.
    It does NOT know about any domain (travel, medical, etc).
    """

    def __init__(
        self,
        task: TaskDefinition,
        context: RuntimeContext,
        webhook: WebhookClient,
        driver: ConversationDriver,
        kore_api: Any = None,
    ):
        self.task = task
        self.context = context
        self.webhook = webhook
        self.driver = driver
        self.kore_api = kore_api

    @abstractmethod
    async def execute(self) -> PatternResult:
        """Execute this pattern. Returns the result with checks and evidence."""
        ...

    def _record_turn(
        self,
        result: PatternResult,
        role: str,
        content: str,
    ) -> None:
        """Record a conversation turn in the result and runtime context."""
        result.transcript_turns.append({"role": role, "content": content})
        transcript = self.context.get_transcript(self.task.task_id)
        if transcript:
            transcript.add_turn(role, content)

    @staticmethod
    def _format_transcript(turns: list[dict[str, str]]) -> str:
        """Format conversation transcript for evidence cards."""
        lines = []
        for turn in turns:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")
            prefix = ">> BOT:" if role == "bot" else "<< USER:"
            # Truncate very long messages
            display = content[:500]
            if len(content) > 500:
                display += "..."
            lines.append(f"{prefix} {display}")
        return "\n\n".join(lines)

    def _analyse_debug_logs(self, result: "PatternResult", debug: dict) -> None:
        """Append debug log analysis as CheckResult entries to the pattern result."""
        from ..core.scoring import CheckStatus

        if "error" in debug:
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.debug_logs",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Debug logs retrieval",
                status=CheckStatus.INFO,
                details=f"Debug logs unavailable: {debug['error']}",
                score=0.0,
                weight=0.0,
            ))
            return

        # Intent match check
        intent_name = debug.get("intentName", "")
        if self.task.dialog_name.lower() not in intent_name.lower():
            result.checks.append(CheckResult(
                check_id=f"webhook.{self.task.task_id}.intent_match",
                task_id=self.task.task_id,
                pipeline="webhook",
                label="Debug log: intent name match",
                status=CheckStatus.WARNING,
                details=(
                    f"Expected dialog '{self.task.dialog_name}' in intent name, "
                    f"but got '{intent_name}'."
                ),
                score=0.0,
                weight=0.0,
            ))

        # Service node payload coverage check
        for call in debug.get("serviceNodeCalls", []):
            request_payload = call.get("requestPayload", {})
            for entity in self.task.required_entities:
                if entity.entity_key not in request_payload:
                    result.checks.append(CheckResult(
                        check_id=f"webhook.{self.task.task_id}.payload.{entity.entity_key}",
                        task_id=self.task.task_id,
                        pipeline="webhook",
                        label=f"Debug log: entity '{entity.entity_key}' in service payload",
                        status=CheckStatus.FAIL,
                        details=(
                            f"Entity '{entity.entity_key}' not found in service node "
                            f"request payload."
                        ),
                        score=0.0,
                        weight=0.0,
                    ))
