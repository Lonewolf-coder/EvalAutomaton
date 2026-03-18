"""Tests for the evaluation retry/resume mechanism."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from governiq.core.engine import EvaluationEngine
from governiq.core.manifest import Manifest
from governiq.core.runtime_context import RuntimeContext, TaskRecord
from governiq.core.scoring import Scorecard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_manifest_dict() -> dict:
    return {
        "manifest_id": "resume-test",
        "assessment_name": "Resume Test",
        "assessment_type": "test",
        "webhook_url": "https://test.example.com/webhook",
        "tasks": [
            {
                "task_id": "task1",
                "task_name": "Welcome",
                "pattern": "WELCOME",
                "dialog_name": "Welcome",
            },
            {
                "task_id": "task2",
                "task_name": "Book",
                "pattern": "CREATE",
                "dialog_name": "Book",
                "required_entities": [
                    {
                        "entity_key": "name",
                        "semantic_hint": "full name",
                        "value_pool": ["Alice", "Bob"],
                    }
                ],
            },
            {
                "task_id": "task3",
                "task_name": "Retrieve",
                "pattern": "RETRIEVE",
                "dialog_name": "Retrieve",
            },
        ],
    }


def _make_engine(tmp_path: Path) -> EvaluationEngine:
    manifest = Manifest(**_minimal_manifest_dict())
    return EvaluationEngine(manifest=manifest, persist_dir=str(tmp_path))


def _write_saved_scorecard(tmp_path: Path, session_id: str, completed_tasks: list[str]) -> None:
    """Write a minimal saved scorecard JSON simulating a partial run."""
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "session_id": session_id,
        "candidate_id": "test-candidate",
        "manifest_id": "resume-test",
        "assessment_name": "Resume Test",
        "overall_score": 0.5,
        "has_critical_failures": False,
        "any_webhook_tested": True,
        "state_seeded": False,
        "task_scores": [
            {"task_id": "task1", "task_name": "Welcome",
             "cbm_score": 0.0, "webhook_score": 1.0, "combined_score": 1.0,
             "all_passed": True, "webhook_tested": True,
             "cbm_checks": [], "webhook_checks": [], "evidence_cards": []},
            {"task_id": "task2", "task_name": "Book",
             "cbm_score": 0.0, "webhook_score": 0.0, "combined_score": 0.0,
             "all_passed": False, "webhook_tested": False,
             "cbm_checks": [], "webhook_checks": [], "evidence_cards": []},
            {"task_id": "task3", "task_name": "Retrieve",
             "cbm_score": 0.0, "webhook_score": 0.0, "combined_score": 0.0,
             "all_passed": False, "webhook_tested": False,
             "cbm_checks": [], "webhook_checks": [], "evidence_cards": []},
        ],
        "compliance_results": [],
        "faq_score": 0.0,
        "kore_api_insights": {},
        "analytics_by_task": {},
        "completed_tasks": completed_tasks,
        "task_sessions": {},
        "eval_window": {},
        "analytics_status": "pending",
        "analytics_last_checked_at": None,
        "state_seed_tasks": [],
    }
    with (results_dir / f"scorecard_{session_id}.json").open("w") as f:
        json.dump(data, f)


def _write_saved_context(tmp_path: Path, session_id: str) -> None:
    """Write a minimal saved RuntimeContext simulating a partial run."""
    ctx = RuntimeContext(
        session_id=session_id,
        candidate_id="test-candidate",
        manifest_id="resume-test",
    )
    ctx.cache_record(TaskRecord(
        record_alias="Booking1",
        task_id="task2",
        fields={"name": "Alice"},
    ))
    ctx.task_results["task1"] = {"success": True}
    ctx.save(tmp_path / "runtime_contexts")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResumeMechanism:

    def test_completed_tasks_persisted_in_scorecard(self, tmp_path):
        """completed_tasks appears in to_dict output."""
        sc = Scorecard(
            session_id="abc",
            candidate_id="c1",
            manifest_id="m1",
            assessment_name="Test",
            completed_tasks=["task1", "task2"],
        )
        d = sc.to_dict()
        assert "completed_tasks" in d
        assert d["completed_tasks"] == ["task1", "task2"]

    def test_completed_tasks_empty_by_default(self):
        sc = Scorecard(
            session_id="abc",
            candidate_id="c1",
            manifest_id="m1",
            assessment_name="Test",
        )
        assert sc.completed_tasks == []

    def test_resume_raises_if_no_scorecard(self, tmp_path):
        engine = _make_engine(tmp_path)
        with pytest.raises(FileNotFoundError, match="Scorecard not found"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                engine.resume_evaluation("nonexistent-id")
            )

    def test_resume_raises_if_no_context(self, tmp_path):
        engine = _make_engine(tmp_path)
        session_id = "partial-001"
        _write_saved_scorecard(tmp_path, session_id, completed_tasks=["task1"])
        # No context file written
        with pytest.raises(FileNotFoundError, match="RuntimeContext not found"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                engine.resume_evaluation(session_id)
            )

    @pytest.mark.asyncio
    async def test_resume_skips_completed_tasks(self, tmp_path):
        """Resume only calls _run_webhook_pipeline for incomplete tasks."""
        engine = _make_engine(tmp_path)
        session_id = "partial-002"
        _write_saved_scorecard(tmp_path, session_id, completed_tasks=["task1"])
        _write_saved_context(tmp_path, session_id)

        executed_tasks: list[str] = []

        async def fake_pipeline(context, scorecard, skip_task_ids=None):
            for task in engine.manifest.tasks:
                if task.task_id not in (skip_task_ids or set()):
                    executed_tasks.append(task.task_id)
            return {}

        with patch.object(engine, "_run_webhook_pipeline", side_effect=fake_pipeline):
            scorecard = await engine.resume_evaluation(session_id)

        # task1 was already completed — should not appear in executed list
        assert "task1" not in executed_tasks
        assert "task2" in executed_tasks
        assert "task3" in executed_tasks

    @pytest.mark.asyncio
    async def test_webhook_pipeline_skips_listed_tasks(self, tmp_path):
        """_run_webhook_pipeline respects skip_task_ids."""
        engine = _make_engine(tmp_path)
        context = RuntimeContext(session_id="s1", candidate_id="c1", manifest_id="m1")
        scorecard = Scorecard(
            session_id="s1", candidate_id="c1",
            manifest_id="m1", assessment_name="Test",
        )

        ran: list[str] = []

        async def fake_execute(self_inner):
            ran.append(self_inner.task.task_id)
            result = MagicMock()
            result.success = True
            result.checks = []
            result.evidence_cards = []
            return result

        # Mock everything the pipeline needs so it doesn't try to connect
        engine.webhook_client = MagicMock()
        engine.webhook_client.close = AsyncMock()
        engine.driver = MagicMock()
        engine.state_inspector = MagicMock()
        engine.state_inspector.verify_task = AsyncMock(return_value=([], []))

        with patch("governiq.core.engine.get_pattern_executor") as mock_get:
            def _side_effect(pattern):
                class Executor:
                    def __init__(self_inner, task, context, webhook, driver, kore_api):
                        self_inner.task = task
                    async def execute(self_inner):
                        ran.append(self_inner.task.task_id)
                        result = MagicMock()
                        result.success = True
                        result.checks = []
                        result.evidence_cards = []
                        return result
                return Executor

            mock_get.side_effect = _side_effect
            await engine._run_webhook_pipeline(
                context, scorecard,
                skip_task_ids={"task1", "task3"},
            )

        assert "task1" not in ran
        assert "task3" not in ran
        assert "task2" in ran
