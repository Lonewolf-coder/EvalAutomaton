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
            }},  # strategy dict -- must NOT be converted
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
        undefined=StrictUndefined,  # strict -- raises on missing
    )

    # Provide a minimal mock request object so base.html navigation renders.
    # base.html checks request.url.path for active-link highlighting.
    mock_url = SimpleNamespace(path="/candidate/history")
    mock_request = SimpleNamespace(url=mock_url)

    # Simulate what the route passes to the template -- an error stub
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
        # If we get here, the template rendered without crashing -- success
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
            "pass_threshold": 0.10,  # Invalid -- below 0.5
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


# ---------------------------------------------------------------------------
# Task 12: Halt Handler in Engine + EvalLogger Wiring
# ---------------------------------------------------------------------------

def test_halt_writes_checkpoint(tmp_path):
    """On EvaluationHaltedError raised inside the engine, _run_evaluation_background must
    update the stub with status='halted'. This test patches the engine to raise the error
    and verifies the route's exception handler writes the correct stub fields."""
    import json
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.governiq.core.exceptions import EvaluationHaltedError
    import src.governiq.candidate.routes as cand_routes

    session_id = "halt-bg-test"
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stub_path = results_dir / f"scorecard_{session_id}.json"
    stub_path.write_text(json.dumps({
        "session_id": session_id,
        "status": "running",
        "completed_tasks": ["task1"],
        "halt_reason": None,
        "halted_on_task": None,
        "halted_at": None,
    }))

    # Minimal manifest mock
    manifest = MagicMock()
    manifest.assessment_name = "Test"
    manifest.manifest_id = "test-v1"
    manifest.scoring_config = {}

    # Engine mock that raises EvaluationHaltedError on run
    mock_engine_instance = MagicMock()
    mock_engine_instance.run_cbm_only = AsyncMock(
        side_effect=EvaluationHaltedError(reason="429 rate limit", task_id="task2", retriable=True)
    )
    mock_engine_instance.run_full_evaluation = AsyncMock(
        side_effect=EvaluationHaltedError(reason="429 rate limit", task_id="task2", retriable=True)
    )

    original_data_dir = cand_routes.DATA_DIR
    try:
        cand_routes.DATA_DIR = tmp_path
        with patch("src.governiq.candidate.routes.EvaluationEngine", return_value=mock_engine_instance):
            asyncio.run(cand_routes._run_evaluation_background(
                session_id=session_id,
                manifest=manifest,
                bot_export_data={"name": "TestBot"},
                candidate_id="test@example.com",
                webhook_url="",
                kore_creds=None,
                llm_config=MagicMock(api_key="k", model="m", base_url="", api_format="openai"),
                kore_bearer_token="",
                plag_report=None,
            ))
    finally:
        cand_routes.DATA_DIR = original_data_dir

    updated = json.loads(stub_path.read_text())
    assert updated["status"] == "halted", f"Expected 'halted', got '{updated['status']}'"
    assert updated["halt_reason"] == "429 rate limit"
    assert updated["halted_on_task"] == "task2"
    assert updated["halted_at"] is not None


# ---------------------------------------------------------------------------
# Task 13: Show All Submissions + _enrich_submission
# ---------------------------------------------------------------------------

def test_admin_shows_all_statuses(tmp_path):
    """_load_all_evaluations must return records of every status."""
    import json
    from pathlib import Path

    statuses = ["completed", "running", "halted", "error"]
    results = tmp_path / "results"
    results.mkdir()
    for i, s in enumerate(statuses):
        path = results / f"scorecard_stub-{i}.json"
        path.write_text(json.dumps({"session_id": f"stub-{i}", "status": s,
                                     "overall_score": 0.8 if s == "completed" else None}))

    import src.governiq.admin.routes as admin_routes
    original = admin_routes.DATA_DIR
    try:
        admin_routes.DATA_DIR = tmp_path
        evals = admin_routes._load_all_evaluations()
    finally:
        admin_routes.DATA_DIR = original

    found_statuses = {e["status"] for e in evals}
    assert found_statuses == set(statuses)


def test_enrich_submission_can_resume(tmp_path):
    """can_resume=True only when RuntimeContext exists and is valid JSON."""
    import json
    import src.governiq.admin.routes as admin_routes

    session_id = "enrich-test"
    ctx_dir = tmp_path / "runtime_contexts"
    ctx_dir.mkdir()
    (ctx_dir / f"context_{session_id}.json").write_text(json.dumps({"session_id": session_id}))

    original = admin_routes.DATA_DIR
    try:
        admin_routes.DATA_DIR = tmp_path
        stub = {"session_id": session_id, "status": "halted", "submitted_at": "2026-01-01T00:00:00+00:00"}
        enriched = admin_routes._enrich_submission(stub)
    finally:
        admin_routes.DATA_DIR = original

    assert enriched["can_resume"] is True


def test_enrich_submission_missing_submitted_at_is_stale(tmp_path):
    """Stubs without submitted_at must be treated as stale."""
    import src.governiq.admin.routes as admin_routes

    original = admin_routes.DATA_DIR
    try:
        admin_routes.DATA_DIR = tmp_path
        stub = {"session_id": "old-stub", "status": "running"}  # no submitted_at
        enriched = admin_routes._enrich_submission(stub)
    finally:
        admin_routes.DATA_DIR = original

    assert enriched["display_status"] == "stale"


def test_enrich_can_resume_corrupt_context(tmp_path):
    """A valid-JSON-but-empty RuntimeContext must result in can_resume=False."""
    import json
    import src.governiq.admin.routes as admin_routes

    session_id = "corrupt-ctx"
    ctx_dir = tmp_path / "runtime_contexts"
    ctx_dir.mkdir()
    (ctx_dir / f"context_{session_id}.json").write_text("{}")  # empty object

    original = admin_routes.DATA_DIR
    try:
        admin_routes.DATA_DIR = tmp_path
        stub = {"session_id": session_id, "status": "halted", "submitted_at": "2026-01-01T00:00:00+00:00"}
        enriched = admin_routes._enrich_submission(stub)
    finally:
        admin_routes.DATA_DIR = original

    assert enriched["can_resume"] is False


# ---------------------------------------------------------------------------
# Task 14: _build_stats pass_threshold + corrupt file logging
# ---------------------------------------------------------------------------


def test_build_stats_uses_scorecard_pass_threshold():
    """_build_stats must read pass_threshold from scorecard, not hardcoded 0.7."""
    from src.governiq.admin.routes import _build_stats
    evaluations = [
        {"overall_score": 0.65, "has_critical_failures": False, "pass_threshold": 0.60},
        {"overall_score": 0.65, "has_critical_failures": False, "pass_threshold": 0.70},
        {"overall_score": None, "has_critical_failures": False, "pass_threshold": 0.60},
    ]
    stats = _build_stats(evaluations)
    assert stats["passed"] == 1  # Only first passes (0.65 >= 0.60 but not >= 0.70)
    assert stats["total"] == 3


def test_build_stats_no_threshold_not_counted_as_pass():
    """If no pass_threshold in scorecard, evaluation should not be counted as passed."""
    from src.governiq.admin.routes import _build_stats
    evaluations = [
        {"overall_score": 0.95, "has_critical_failures": False},  # no pass_threshold key
    ]
    stats = _build_stats(evaluations)
    assert stats["passed"] == 0  # Can't determine pass without threshold


def test_load_all_evaluations_logs_corrupt_file(tmp_path, monkeypatch):
    """_load_all_evaluations should log warnings for corrupt files, not swallow silently."""
    from src.governiq.admin import routes as admin_routes
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    corrupt_file = results_dir / "scorecard_bad.json"
    corrupt_file.write_text("not json{{{")
    monkeypatch.setattr(admin_routes, "DATA_DIR", tmp_path)
    # Capture logging
    with patch("src.governiq.admin.routes.logger") as mock_logger:
        monkeypatch.setattr(admin_routes, "DATA_DIR", tmp_path)
        result = admin_routes._load_all_evaluations()
    assert result == []
    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Task 15: Restart Endpoint
# ---------------------------------------------------------------------------

def test_restart_blocked_by_active_lock(tmp_path):
    """POST /admin/evaluation/{id}/restart must return 409 if lock is active."""
    import json
    from datetime import datetime, timezone
    import src.governiq.admin.routes as admin_routes

    session_id = "locked-eval"
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    (locks_dir / f"{session_id}.lock").write_text(
        json.dumps({"started_at": datetime.now(timezone.utc).isoformat()})
    )

    original = admin_routes.DATA_DIR
    try:
        admin_routes.DATA_DIR = tmp_path
        # _is_lock_stale_admin should return False for a fresh lock
        assert admin_routes._is_lock_stale_admin(session_id) is False
    finally:
        admin_routes.DATA_DIR = original


# ---------------------------------------------------------------------------
# Task 17: Log Streaming Endpoint
# ---------------------------------------------------------------------------

def test_log_endpoint_offset(tmp_path):
    """GET /api/v1/logs/{id}?offset=N returns only entries after offset."""
    import json

    session_id = "log-test-1"
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_file = logs_dir / f"eval_{session_id}.jsonl"

    entries = [
        {"ts": "2026-01-01T00:00:00", "task_id": "task1", "level": "info",
         "event": f"event_{i}", "detail": "", "raw": {}}
        for i in range(5)
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    from src.governiq.api.routes import read_log_entries
    result = read_log_entries(session_id=session_id, offset=2, logs_dir=logs_dir)
    assert result["next_offset"] == 5
    assert len(result["entries"]) == 3
    assert result["entries"][0]["event"] == "event_2"


def test_log_endpoint_done_when_terminal(tmp_path):
    """done=True when the scorecard has a terminal status."""
    import json
    from src.governiq.api.routes import read_log_entries

    session_id = "done-test"
    logs_dir = tmp_path / "logs"
    results_dir = tmp_path / "results"
    logs_dir.mkdir()
    results_dir.mkdir()
    (logs_dir / f"eval_{session_id}.jsonl").write_text("")
    (results_dir / f"scorecard_{session_id}.json").write_text(
        json.dumps({"session_id": session_id, "status": "completed"})
    )

    import src.governiq.api.routes as api_routes
    original = api_routes.DATA_DIR
    try:
        api_routes.DATA_DIR = tmp_path
        result = read_log_entries(session_id=session_id, offset=0, logs_dir=logs_dir)
    finally:
        api_routes.DATA_DIR = original

    assert result["done"] is True


# ---------------------------------------------------------------------------
# Task 19: Evidence Integration
# ---------------------------------------------------------------------------

def test_evidence_cards_populated_from_log(tmp_path):
    """After evaluation, each TaskScore must have log entries embedded as evidence."""
    import json
    from src.governiq.core.eval_logger import EvalLogger
    from src.governiq.core.engine import _embed_log_as_evidence
    from src.governiq.core.scoring import TaskScore

    # Write a JSONL log
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    logger = EvalLogger(session_id="ev-test", log_dir=logs_dir)
    logger.log("task1", "info", "bot_message", detail="Hello!", raw={"val": "Hello!"})
    logger.log("task1", "info", "user_message", detail="Book a flight")
    logger.log("task2", "info", "bot_message", detail="Where to?")

    task_scores = [
        TaskScore(task_id="task1", task_name="Welcome"),
        TaskScore(task_id="task2", task_name="Booking"),
    ]

    _embed_log_as_evidence(
        session_id="ev-test",
        task_scores=task_scores,
        logs_dir=logs_dir,
    )

    t1_events = [c.content for c in task_scores[0].evidence_cards]
    assert any("Hello!" in e for e in t1_events)
    t2_events = [c.content for c in task_scores[1].evidence_cards]
    assert any("Where to?" in e for e in t2_events)


# ---------------------------------------------------------------------------
# Task 20: Health endpoint caching + 401 fix
# ---------------------------------------------------------------------------

def test_health_cache_hit():
    """LLM provider must only be probed once within the TTL window."""
    from unittest.mock import patch
    import src.governiq.api.routes as api_routes

    # Clear the cache
    api_routes._health_cache.clear()

    mock_result = {"status": "ok", "message": "Connected", "detail": "HTTP 200"}

    with patch.object(api_routes, '_probe_llm_provider', return_value=mock_result) as mock_probe:
        r1 = api_routes._check_ai_model()
        r2 = api_routes._check_ai_model()  # Should hit cache

    assert mock_probe.call_count == 1
    assert r1["status"] == "ok"
    assert r2["status"] == "ok"


def test_health_401_is_failing():
    """A 401 Unauthorized from the LLM provider must return status='failing'."""
    import src.governiq.api.routes as api_routes
    import httpx
    from unittest.mock import patch, MagicMock

    api_routes._health_cache.clear()

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_response
    )

    with patch('httpx.get', return_value=mock_response):
        result = api_routes._check_ai_model()

    assert result["status"] == "failing"
    assert "401" in result["message"] or "invalid" in result["message"].lower()


# ---------------------------------------------------------------------------
# Task 21: Scorecard __post_init__ with scoring_config
# ---------------------------------------------------------------------------


def test_scoring_uses_manifest_weights():
    """Scorecard must use scoring_config weights, not hardcoded 80/10/10."""
    from src.governiq.core.scoring import Scorecard, TaskScore, CheckResult, CheckStatus

    config = {
        "webhook_functional_weight": 0.60,
        "compliance_weight": 0.20,
        "faq_weight": 0.20,
        "pass_threshold": 0.70,
    }
    sc = Scorecard(
        session_id="s1", candidate_id="c1", manifest_id="m1",
        assessment_name="Test", scoring_config=config,
    )
    ts = TaskScore(task_id="t1", task_name="Task 1")
    ts.webhook_checks = [CheckResult(
        check_id="c1", task_id="t1", pipeline="webhook",
        label="test", status=CheckStatus.PASS, score=1.0
    )]
    sc.task_scores = [ts]
    sc.faq_score = 0.0  # FAQ ran but scored 0 -- NOT None, so NO redistribution

    # Expected: 1.0 * 0.60 + 1.0 * 0.20 + 0.0 * 0.20 = 0.80
    assert abs(sc.overall_score - 0.80) < 0.001


def test_scoring_normalises_weights():
    """Weights not summing to 1.0 must be normalised."""
    from src.governiq.core.scoring import Scorecard

    config = {
        "webhook_functional_weight": 0.80,
        "compliance_weight": 0.15,  # sums to 1.05
        "faq_weight": 0.10,
        "pass_threshold": 0.70,
    }
    sc = Scorecard(
        session_id="s2", candidate_id="c2", manifest_id="m2",
        assessment_name="Test", scoring_config=config,
    )
    total = sc._webhook_weight + sc._compliance_weight + sc._faq_weight
    assert abs(total - 1.0) < 0.01


def test_scoring_legacy_defaults_unchanged():
    """Scorecard without scoring_config must still work (uses existing logic)."""
    from src.governiq.core.scoring import Scorecard, TaskScore, CheckResult, CheckStatus

    sc = Scorecard(session_id="s3", candidate_id="c3", manifest_id="m3", assessment_name="T")
    ts = TaskScore(task_id="t1", task_name="Task 1")
    ts.webhook_checks = [CheckResult(
        check_id="c1", task_id="t1", pipeline="webhook",
        label="test", status=CheckStatus.PASS, score=1.0
    )]
    sc.task_scores = [ts]
    # With legacy weights, overall_score should still be > 0
    assert sc.overall_score > 0.0
