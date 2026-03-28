"""Tests for EvaluationEngine.run_gate0() and related gate-wiring behaviour."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from governiq.core.gate0 import Gate0Result, Gate0CheckStatus


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_engine(tmp_path):
    """Create a minimal EvaluationEngine instance for gate0 testing."""
    from governiq.core.engine import EvaluationEngine
    from governiq.core.manifest import Manifest

    manifest_path = Path(__file__).parent.parent / "manifests" / "medical_appointment_basic.json"
    manifest_data = json.loads(manifest_path.read_text())
    manifest_data["webhook_url"] = "https://bots.kore.ai/chatbot/v2/fake"
    manifest_data["mock_api_base_url"] = ""

    manifest = Manifest(**manifest_data)
    engine = EvaluationEngine(manifest=manifest, persist_dir=str(tmp_path))
    return engine


# ---------------------------------------------------------------------------
# TestRunGate0
# ---------------------------------------------------------------------------

class TestRunGate0:
    @pytest.mark.asyncio
    async def test_pass_stores_result(self, minimal_engine):
        """Passing Gate 0 stores gate0_result on engine."""
        passing_result = Gate0Result(checks={
            "webhook_version": Gate0CheckStatus.PASS,
            "webhook_reachability": Gate0CheckStatus.PASS,
            "backend_api": Gate0CheckStatus.SKIP,
            "bot_credentials": Gate0CheckStatus.SKIP,
            "bot_published": Gate0CheckStatus.SKIP,
            "web_channel": Gate0CheckStatus.SKIP,
        }, messages={})

        with patch("governiq.core.engine.Gate0Checker") as MockChecker:
            MockChecker.return_value.run = AsyncMock(return_value=passing_result)
            result = await minimal_engine.run_gate0()

        assert minimal_engine.gate0_result is passing_result
        assert result.can_proceed is True

    @pytest.mark.asyncio
    async def test_fail_raises_value_error(self, minimal_engine):
        """Failing Gate 0 raises ValueError with the failure message."""
        failing_result = Gate0Result(
            checks={"webhook_version": Gate0CheckStatus.FAIL},
            messages={"webhook_version": "V1 URL not supported"},
        )

        with patch("governiq.core.engine.Gate0Checker") as MockChecker:
            MockChecker.return_value.run = AsyncMock(return_value=failing_result)
            with pytest.raises(ValueError, match="Gate 0 failed"):
                await minimal_engine.run_gate0()

        assert minimal_engine.gate0_result is failing_result


# ---------------------------------------------------------------------------
# TestPreGate2Probe — inline probe inside run_full_evaluation
# ---------------------------------------------------------------------------

class TestPreGate2Probe:
    @pytest.mark.asyncio
    async def test_404_raises_failed_connectivity(self, minimal_engine, tmp_path):
        """A 404 from the pre-Gate2 webhook probe raises FAILED_CONNECTIVITY ValueError."""
        # Provide a minimal valid bot export so parsing doesn't fail before the probe
        bot_export = {
            "name": "TestBot",
            "dialogs": [],
            "faqs": [],
            "intentModels": [],
        }

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.head = AsyncMock(return_value=mock_response)

        with patch("governiq.core.engine.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="FAILED_CONNECTIVITY"):
                await minimal_engine.run_full_evaluation(
                    bot_export=bot_export,
                    candidate_id="test-candidate",
                    session_id="test-session-404",
                )


# ---------------------------------------------------------------------------
# TestWebDriverSkip
# ---------------------------------------------------------------------------

class TestWebDriverSkip:
    @pytest.mark.asyncio
    async def test_web_driver_task_skipped_when_no_web_channel(self, minimal_engine):
        """Tasks with ui_policy=WEB_DRIVER are skipped when web channel not available."""
        from governiq.core.manifest import UIPolicy

        # Set gate0 result with web_channel WARN (not available)
        minimal_engine.gate0_result = Gate0Result(
            checks={"web_channel": Gate0CheckStatus.WARN},
            messages={"web_channel": "Web channel not enabled"},
        )
        assert not minimal_engine.gate0_result.web_channel_available

        # Check a WEB_DRIVER task would be skipped
        task = minimal_engine.manifest.tasks[0]
        task.ui_policy = UIPolicy.WEB_DRIVER

        should_skip = (
            task.ui_policy == UIPolicy.WEB_DRIVER
            and minimal_engine.gate0_result is not None
            and not minimal_engine.gate0_result.web_channel_available
        )
        assert should_skip is True
