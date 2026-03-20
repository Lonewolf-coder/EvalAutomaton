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
        "tasks": [
            {
                "task_id": "task1",
                "task_name": "Test Task",
                "pattern": "CREATE",
                "dialog_name": "TestDialog",
            }
        ],
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


def test_submit_saves_bot_export_to_uploads(tmp_path):
    """Bot export file must be saved under DATA_DIR/uploads/{session_id}/ after a submission."""
    import io
    from fastapi.testclient import TestClient

    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    manifest_data = {
        "manifest_id": "test-manifest-v1",
        "assessment_name": "Test Assessment",
        "assessment_type": "test",
        "tasks": [
            {
                "task_id": "task1",
                "task_name": "Test Task",
                "pattern": "CREATE",
                "dialog_name": "TestDialog",
            }
        ],
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

        upload_dir = tmp_path / "uploads" / session_id
        assert upload_dir.exists(), f"Upload directory not created at {upload_dir}"
        uploaded_files = list(upload_dir.iterdir())
        assert len(uploaded_files) > 0, "No files written to upload directory"
        assert any(f.name.startswith("bot_export") for f in uploaded_files), (
            f"No bot_export file found in {upload_dir}; found: {[f.name for f in uploaded_files]}"
        )
    finally:
        for p in patches:
            p.stop()


def test_zip_cleanup_skips_active_lock(tmp_path):
    """cleanup_old_uploads must NOT delete an upload if a lock file exists for that session."""
    from src.governiq.candidate.routes import cleanup_old_uploads

    uploads = tmp_path / "uploads"
    locks = tmp_path / "locks"
    uploads.mkdir()
    locks.mkdir()

    session_id = "locked-session"
    upload_dir = uploads / session_id
    upload_dir.mkdir()
    (upload_dir / "bot_export.zip").write_bytes(b"fake")

    # Write a lock file for this session
    (locks / f"{session_id}.lock").write_text('{"started_at": "2020-01-01T00:00:00+00:00"}')

    # Run cleanup with 0-day retention (everything would normally be deleted)
    cleanup_old_uploads(uploads_dir=uploads, locks_dir=locks, max_age_days=0)

    # Upload must still exist because of the lock
    assert (upload_dir / "bot_export.zip").exists()


def test_lock_created_and_deleted(tmp_path):
    """Lock file must exist during evaluation and be deleted after completion."""
    from src.governiq.candidate.routes import _create_lock, _delete_lock, _is_lock_stale

    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    session_id = "lock-test-999"

    _create_lock(session_id, locks_dir=locks_dir)
    lock_path = locks_dir / f"{session_id}.lock"
    assert lock_path.exists()

    data = json.loads(lock_path.read_text())
    assert "started_at" in data

    _delete_lock(session_id, locks_dir=locks_dir)
    assert not lock_path.exists()


def test_stale_lock_detection(tmp_path):
    """A lock older than 15 minutes is stale."""
    from src.governiq.candidate.routes import _create_lock, _is_lock_stale
    from datetime import datetime, timezone, timedelta

    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    session_id = "stale-lock-test"

    # Write a lock with an old timestamp
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    (locks_dir / f"{session_id}.lock").write_text(json.dumps({"started_at": old_time}))

    assert _is_lock_stale(session_id, locks_dir=locks_dir) is True

    # Fresh lock is not stale
    _create_lock(session_id, locks_dir=locks_dir)
    assert _is_lock_stale(session_id, locks_dir=locks_dir) is False


def test_value_pool_dict_normalised_at_load():
    """A value_pool authored as a JSON object must be converted to a list at load time.
    Strategy dicts (with 'strategy' key) must be preserved unchanged."""
    from src.governiq.core.manifest import normalise_value_pools

    task_data = {
        "task_id": "t1",
        "required_entities": [
            {"entity_key": "city", "value_pool": {"0": "London", "1": "Paris", "2": "Rome"}},
            {"entity_key": "date", "value_pool": ["2026-01-01", "2026-02-01"]},  # already a list
            {"entity_key": "dept_date", "value_pool": {
                "strategy": "relative_days_from_today",
                "offsets": [7, 14, 21],
                "format": "DD-MM-YYYY",
            }},  # strategy dict — must NOT be converted
        ],
    }
    normalise_value_pools(task_data)

    entities = task_data["required_entities"]
    assert isinstance(entities[0]["value_pool"], list)
    assert set(entities[0]["value_pool"]) == {"London", "Paris", "Rome"}
    assert entities[1]["value_pool"] == ["2026-01-01", "2026-02-01"]  # unchanged
    assert isinstance(entities[2]["value_pool"], dict)  # strategy dict preserved
    assert entities[2]["value_pool"]["strategy"] == "relative_days_from_today"


def test_manifest_loads_with_dict_value_pool():
    """Manifest model validator must normalise dict value_pools at construction time."""
    from src.governiq.core.manifest import Manifest

    manifest_data = {
        "manifest_id": "test-vpool",
        "assessment_name": "Test",
        "assessment_type": "test",
        "tasks": [
            {
                "task_id": "t1",
                "task_name": "Task 1",
                "pattern": "CREATE",
                "dialog_name": "TestDialog",
                "required_entities": [
                    {
                        "entity_key": "city",
                        "semantic_hint": "A city",
                        "value_pool": {"0": "London", "1": "Paris"},
                    }
                ],
            }
        ],
    }
    m = Manifest(**manifest_data)
    vp = m.tasks[0].required_entities[0].value_pool
    assert isinstance(vp, list)
    assert set(vp) == {"London", "Paris"}


def test_template_guard_error_stub():
    """Rendering candidate_history with an error stub must not raise UndefinedError."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from pathlib import Path
    from types import SimpleNamespace

    template_dir = Path("src/governiq/templates")
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,  # strict — raises on missing
    )

    # Provide a minimal mock request object so base.html navigation renders.
    # base.html checks request.url.path for active-link highlighting.
    mock_url = SimpleNamespace(path="/candidate/history")
    mock_request = SimpleNamespace(url=mock_url)

    # Simulate what the route passes to the template — an error stub
    error_stub = {
        "session_id": "err-stub-1",
        "status": "error",
        "candidate_id": "test@example.com",
        "assessment_name": "Test Assessment",
        # Intentionally missing: overall_score, task_scores, has_critical_failures
        "error": "LLM call failed",
    }

    try:
        template = env.get_template("candidate_history.html")
        rendered = template.render(
            request=mock_request,
            portal="candidate",
            submissions=[error_stub],
        )
        # If we get here, the template rendered without crashing — success
        assert "err-stub-1" in rendered or "error" in rendered.lower()
    except Exception as e:
        pytest.fail(f"Template raised an exception for error stub: {e}")


def test_validate_manifest_data_valid():
    from src.governiq.admin.routes import validate_manifest_data
    data = {
        "manifest_id": "test-v1",
        "tasks": [
            {"task_id": "t1", "required_entities": [{"entity_key": "x", "value_pool": ["a", "b"]}]}
        ],
        "scoring_config": {
            "webhook_functional_weight": 0.80,
            "compliance_weight": 0.10,
            "faq_weight": 0.10,
            "pass_threshold": 0.70,
        },
    }
    result = validate_manifest_data(data)
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_manifest_data_bad_threshold():
    from src.governiq.admin.routes import validate_manifest_data
    data = {
        "manifest_id": "test-v1",
        "tasks": [],
        "scoring_config": {
            "webhook_functional_weight": 0.80,
            "compliance_weight": 0.10,
            "faq_weight": 0.10,
            "pass_threshold": 0.10,  # Invalid — below 0.5
        },
    }
    result = validate_manifest_data(data)
    assert result["valid"] is False
    assert any("pass_threshold" in e for e in result["errors"])


def test_validate_manifest_data_warnings_only():
    from src.governiq.admin.routes import validate_manifest_data
    data = {
        "manifest_id": "test-v1",
        "tasks": [
            {"task_id": "t1", "required_entities": [{"entity_key": "x", "value_pool": {"0": "a"}}]}
        ],
        "scoring_config": {
            "webhook_functional_weight": 0.80,
            "compliance_weight": 0.10,
            "faq_weight": 0.10,
            "pass_threshold": 0.70,
        },
    }
    result = validate_manifest_data(data)
    assert result["valid"] is True  # Warnings don't block save
    assert len(result["warnings"]) > 0
    assert any("value_pool" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Task 10: EvaluationHaltedError
# ---------------------------------------------------------------------------

def test_evaluation_halted_error_attributes():
    from src.governiq.core.exceptions import EvaluationHaltedError
    err = EvaluationHaltedError(reason="429 Too Many Requests", task_id="task2", retriable=True)
    assert err.reason == "429 Too Many Requests"
    assert err.task_id == "task2"
    assert err.retriable is True

    err2 = EvaluationHaltedError(reason="401 Unauthorized", task_id="task1", retriable=False)
    assert err2.retriable is False

    # Must be catchable as Exception
    try:
        raise err
    except Exception as e:
        assert "429" in str(e.reason)


# ---------------------------------------------------------------------------
# Task 11: Retry-Once Then Halt in driver.py
# ---------------------------------------------------------------------------

def test_halt_on_429_after_retry():
    """LLM returning 429 twice should raise EvaluationHaltedError after one retry."""
    import asyncio
    from unittest.mock import AsyncMock, patch, MagicMock
    from src.governiq.webhook.driver import LLMConversationDriver
    from src.governiq.core.exceptions import EvaluationHaltedError

    driver = LLMConversationDriver(api_key="fake", api_format="openai", base_url="http://fake")

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = Exception("429 Too Many Requests")

    with patch.object(driver, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_client

        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(EvaluationHaltedError) as exc_info:
                asyncio.run(
                    driver._llm_call("sys", "user", task_id="task1")
                )
        assert exc_info.value.task_id == "task1"
        assert exc_info.value.retriable is True


def test_retry_success_on_first_429():
    """LLM returning 429 once then 200 should succeed without halting."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.governiq.webhook.driver import LLMConversationDriver

    driver = LLMConversationDriver(api_key="fake", api_format="openai", base_url="http://fake")

    fail_response = MagicMock()
    fail_response.raise_for_status.side_effect = Exception("429 Too Many Requests")

    ok_response = MagicMock()
    ok_response.raise_for_status = MagicMock()
    ok_response.json.return_value = {"choices": [{"message": {"content": "Hello"}}]}

    with patch.object(driver, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[fail_response, ok_response])
        mock_get_client.return_value = mock_client

        with patch("asyncio.sleep", new=AsyncMock()):
            result = asyncio.run(
                driver._llm_call("sys", "user", task_id="task1")
            )
        assert result == "Hello"
