"""Tests for the WELCOME pattern executor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from governiq.core.manifest import EnginePattern, Manifest, TaskDefinition
from governiq.core.runtime_context import RuntimeContext
from governiq.core.scoring import CheckStatus
from governiq.patterns import PATTERN_REGISTRY, get_pattern_executor
from governiq.patterns.welcome import WelcomePattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(**kwargs) -> TaskDefinition:
    defaults = dict(
        task_id="task1",
        task_name="Welcome",
        pattern=EnginePattern.WELCOME,
        dialog_name="Welcome",
        required_greeting_text="Welcome",
        required_menu_items=["Book Flight", "Fetch Booking"],
        optional_menu_items=["FAQ"],
    )
    defaults.update(kwargs)
    return TaskDefinition(**defaults)


def _make_executor(task, bot_responses: list[str]) -> WelcomePattern:
    context = RuntimeContext(session_id="s1", candidate_id="c1", manifest_id="m1")
    webhook = MagicMock()
    webhook.start_session = AsyncMock()
    webhook.warm_up = AsyncMock()
    responses = iter(bot_responses)
    webhook.send_message = AsyncMock(side_effect=lambda msg: next(responses))
    driver = MagicMock()
    driver.classify_bot_intent = AsyncMock(return_value="information")
    return WelcomePattern(task=task, context=context, webhook=webhook, driver=driver)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestWelcomeRegistry:
    def test_welcome_in_registry(self):
        assert EnginePattern.WELCOME in PATTERN_REGISTRY
        assert PATTERN_REGISTRY[EnginePattern.WELCOME] is WelcomePattern

    def test_get_pattern_executor_welcome(self):
        cls = get_pattern_executor(EnginePattern.WELCOME)
        assert cls is WelcomePattern

    def test_get_pattern_executor_unknown_raises(self):
        with pytest.raises(KeyError, match="No executor registered"):
            get_pattern_executor("NONEXISTENT")  # type: ignore[arg-type]

    def test_all_patterns_registered(self):
        for pattern in EnginePattern:
            assert pattern in PATTERN_REGISTRY, f"{pattern} not in registry"


# ---------------------------------------------------------------------------
# Executor behaviour tests
# ---------------------------------------------------------------------------

class TestWelcomePattern:

    @pytest.mark.asyncio
    async def test_passes_when_greeting_and_all_items_present(self):
        task = _make_task()
        bot_reply = "Welcome! How can I help? Book Flight | Fetch Booking | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is True
        assert result.pattern == "WELCOME"

    @pytest.mark.asyncio
    async def test_fails_when_greeting_missing(self):
        task = _make_task(required_greeting_text="Hello there")
        bot_reply = "Book Flight | Fetch Booking | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is False
        greeting_check = next(
            c for c in result.checks
            if c.check_id.endswith(".greeting")
        )
        assert greeting_check.status == CheckStatus.FAIL

    @pytest.mark.asyncio
    async def test_fails_when_required_item_missing(self):
        task = _make_task()
        # Missing "Fetch Booking" (required) — FAQ (optional) is present
        bot_reply = "Welcome! Book Flight | FAQ only"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is False
        fetch_check = next(
            c for c in result.checks
            if "fetch_booking" in c.check_id
        )
        assert fetch_check.status == CheckStatus.FAIL

    @pytest.mark.asyncio
    async def test_passes_when_only_optional_item_missing(self):
        """Missing optional items → WARNING, full score, task still passes."""
        task = _make_task()
        # Required items present, FAQ (optional) absent
        bot_reply = "Welcome! Book Flight | Fetch Booking"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is True
        faq_check = next(
            c for c in result.checks
            if "optional" in c.check_id and "faq" in c.check_id
        )
        assert faq_check.status == CheckStatus.WARNING
        assert faq_check.score == 1.0  # no score penalty

    @pytest.mark.asyncio
    async def test_optional_item_present_scores_pass(self):
        """When optional item IS present it should be PASS, still score 1.0."""
        task = _make_task()
        bot_reply = "Welcome! Book Flight | Fetch Booking | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        faq_check = next(
            c for c in result.checks
            if "optional" in c.check_id and "faq" in c.check_id
        )
        assert faq_check.status == CheckStatus.PASS
        assert faq_check.score == 1.0

    @pytest.mark.asyncio
    async def test_per_item_checks_emitted(self):
        task = _make_task(required_menu_items=["Book Flight", "Cancel", "FAQ"],
                          optional_menu_items=[])
        bot_reply = "Welcome! Book Flight | Cancel | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        # Only required items — no optional check_ids
        required_checks = [c for c in result.checks if ".menu." in c.check_id and "optional" not in c.check_id]
        assert len(required_checks) == 3
        assert all(c.status == CheckStatus.PASS for c in required_checks)

    @pytest.mark.asyncio
    async def test_no_menu_requirement_passes_menu(self):
        task = _make_task(required_menu_items=[], optional_menu_items=[])
        bot_reply = "Welcome to GovernIQ Travel Agent!"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        menu_checks = [c for c in result.checks if ".menu." in c.check_id]
        assert len(menu_checks) == 0
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_greeting_requirement_passes(self):
        task = _make_task(required_greeting_text="", required_menu_items=[])
        bot_reply = "How can I help?"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_evidence_card_emitted(self):
        task = _make_task()
        bot_reply = "Welcome! Book Flight | Fetch Booking | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        welcome_card = next(
            (c for c in result.evidence_cards if c.card_id.endswith(".welcome")),
            None,
        )
        assert welcome_card is not None
        assert "Greeting found" in welcome_card.content
        assert "Optional items" in welcome_card.content

    @pytest.mark.asyncio
    async def test_evidence_card_notes_missing_optional(self):
        """Evidence card should mention which optional items were absent."""
        task = _make_task()
        bot_reply = "Welcome! Book Flight | Fetch Booking"  # FAQ absent
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        welcome_card = next(c for c in result.evidence_cards if c.card_id.endswith(".welcome"))
        # Card should be green (task passed) but note the missing optional item
        from governiq.core.scoring import EvidenceCardColor
        assert welcome_card.color == EvidenceCardColor.GREEN
        assert "FAQ" in welcome_card.content

    @pytest.mark.asyncio
    async def test_second_turn_used_when_menu_not_in_first_response(self):
        """If first response has no menu items, the executor should send a follow-up."""
        task = _make_task(required_menu_items=["Book Flight", "FAQ"], optional_menu_items=[])
        # First turn: just greeting, no menu
        # Second turn (after follow-up): menu appears
        context = RuntimeContext(session_id="s1", candidate_id="c1", manifest_id="m1")
        webhook = MagicMock()
        webhook.start_session = AsyncMock()
        webhook.warm_up = AsyncMock()
        calls = []
        async def _send(msg):
            calls.append(msg)
            if len(calls) == 1:
                return "Welcome to GovernIQ!"       # no menu yet
            return "Book Flight | FAQ available"    # menu in second response
        webhook.send_message = AsyncMock(side_effect=_send)
        driver = MagicMock()
        driver.classify_bot_intent = AsyncMock(return_value="entity_request")
        executor = WelcomePattern(task=task, context=context, webhook=webhook, driver=driver)
        result = await executor.execute()
        assert len(calls) == 2, "Expected a follow-up turn"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self):
        task = _make_task(
            required_greeting_text="welcome",
            required_menu_items=["BOOK FLIGHT", "fetch booking"],
        )
        bot_reply = "Welcome! Book Flight | Fetch Booking | FAQ"
        executor = _make_executor(task, [bot_reply])
        result = await executor.execute()
        assert result.success is True
