# tests/test_stabilisation.py
import json
from pathlib import Path
from unittest.mock import patch
import pytest


def _make_stub(tmp_path, session_id="abc-123", **extra):
    """Helper: write a minimal stub to tmp_path/results/. Used by other tests."""
    results = tmp_path / "results"
    results.mkdir(parents=True, exist_ok=True)
    stub = {
        "session_id": session_id,
        "status": "running",
        "candidate_id": "cand-1",
        "manifest_id": "travel-v1",
        "assessment_name": "Travel Agent",
        "webhook_url": "https://example.com/webhook",
        "submitted_at": "2026-03-20T08:00:00+00:00",
        "completed_tasks": [],
        "halt_reason": None,
        "halted_on_task": None,
        "halted_at": None,
        "parent_session_id": None,
        "log_file": f"data/logs/eval_{session_id}.jsonl",
        "error": None,
    }
    stub.update(extra)
    path = results / f"scorecard_{session_id}.json"
    path.write_text(json.dumps(stub))
    return path


def test_submit_stub_has_all_required_fields(tmp_path):
    """Stub written by the real /candidate/submit route must contain all enriched schema fields."""
    import io
    from fastapi.testclient import TestClient

    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    manifest_data = {
        "manifest_id": "test-manifest-v1",
        "assessment_name": "Test Assessment",
        "assessment_type": "test",
        "tasks": [],
        "scoring_config": {
            "webhook_functional_weight": 0.80,
            "compliance_weight": 0.10,
            "faq_weight": 0.10,
            "pass_threshold": 0.70,
        },
    }
    (manifests_dir / "test-manifest-v1.json").write_text(json.dumps(manifest_data))

    patches = [
        patch("src.governiq.candidate.routes.DATA_DIR", tmp_path),
        patch("src.governiq.candidate.routes.MANIFESTS_DIR", manifests_dir),
        patch("src.governiq.candidate.routes._run_evaluation_background"),
    ]

    for p in patches:
        p.start()

    try:
        from src.governiq.main import app

        client = TestClient(app, raise_server_exceptions=False)

        bot_export = json.dumps({"name": "TestBot", "intents": []}).encode()
        response = client.post(
            "/candidate/submit",
            data={
                "candidate_name": "Test User",
                "candidate_email": "test@example.com",
                "assessment_type": "test-manifest-v1",
                "mock_api_url": "",
                "mock_api_schema": "",
                "webhook_url": "",
                "bot_id": "",
                "bot_name": "",
                "client_id": "",
                "client_secret": "",
            },
            files={"bot_export": ("bot_export.json", io.BytesIO(bot_export), "application/json")},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        session_id = response.json()["session_id"]

        stub_path = tmp_path / "results" / f"scorecard_{session_id}.json"
        assert stub_path.exists(), "Stub file not written"
        data = json.loads(stub_path.read_text())

        required = [
            "session_id", "status", "candidate_id", "manifest_id",
            "assessment_name", "webhook_url", "submitted_at",
            "completed_tasks", "halt_reason", "halted_on_task",
            "halted_at", "parent_session_id", "log_file", "error",
        ]
        for field in required:
            assert field in data, f"Stub is missing required field: '{field}'"
    finally:
        for p in patches:
            p.stop()
