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
    ):
        self.task = task
        self.context = context
        self.webhook = webhook
        self.driver = driver

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
