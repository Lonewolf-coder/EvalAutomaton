# Stabilisation Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three silent evaluation crashes, give admins full submission visibility with manual re-run controls, add a live webhook log panel, halt evaluations on LLM API errors, fix CSS visibility bugs, cache health checks, and make manifest scoring weights authoritative.

**Architecture:** Six dependency-ordered layers — Storage Foundation → Crash Fixes → Engine Stability → Admin Control → Live Log → Scoring/Health. Each layer depends only on the one above it. All new code is test-driven (write failing test first, then implement).

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, Jinja2, httpx, pytest, local JSON/JSONL file storage.

**Spec:** `docs/superpowers/specs/2026-03-20-stabilisation-sprint-design.md`

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/governiq/core/exceptions.py` | `EvaluationHaltedError` — signals LLM failure requiring admin action |
| `src/governiq/core/eval_logger.py` | Writes structured JSONL log per evaluation session |
| `src/governiq/webhook/message_normaliser.py` | Safe text extraction from all Kore.ai message types |
| `tests/test_eval_logger.py` | Tests for EvalLogger |
| `tests/test_message_normaliser.py` | Tests for message normaliser |
| `tests/test_stabilisation.py` | Integration tests for stub schema, ZIP, lock, halt, health cache, scoring weights |

### Modified files
| File | What changes |
|------|-------------|
| `src/governiq/candidate/routes.py` | Enrich stub, save ZIP, lock lifecycle, halt handler |
| `src/governiq/core/engine.py` | EvalLogger injection via constructor, halt catch, scoring_config pass-through, evidence embedding, extend `resume_evaluation(source_session_id, new_session_id)` |
| `src/governiq/webhook/driver.py` | Use message_normaliser, retry-once then raise EvaluationHaltedError, accept eval_logger |
| `src/governiq/core/scoring.py` | `Scorecard.__post_init__` — consume scoring_config, derive weight attributes, use them in `overall_score` |
| `src/governiq/api/routes.py` | Health cache + 401 fix + `GET /api/v1/logs/{session_id}` endpoint + update resume endpoint |
| `src/governiq/admin/routes.py` | Show all statuses, `_enrich_submission`, restart endpoint, inline key verify, `validate_manifest_data` |
| `src/governiq/templates/candidate_history.html` | Template guard for `overall_score` on stubs |
| `src/governiq/templates/base.html` | CSS select fix, API key show/hide JS, live log panel component (admin only) |
| Admin submission list template (identify exact name at implementation time) | Status badges, re-run buttons, parent/child grouping |
| Admin settings template (identify exact name at implementation time) | Inline verification flash |

---

## Phase 0 — Storage Foundation

### Task 1: Create EvalLogger

**Files:**
- Create: `src/governiq/core/eval_logger.py`
- Create: `tests/test_eval_logger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_logger.py
import json
from pathlib import Path
import pytest
from src.governiq.core.eval_logger import EvalLogger


def test_eval_logger_writes_jsonl(tmp_path):
    logger = EvalLogger(session_id="test-123", log_dir=tmp_path)
    logger.log(task_id="task1", level="info", event="task_start", detail="Starting task1")
    logger.log(task_id="task1", level="info", event="bot_message", detail="Hello", raw={"text": "Hello"})

    log_file = tmp_path / "eval_test-123.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["task_id"] == "task1"
    assert entry["event"] == "task_start"
    assert "ts" in entry
    assert entry["raw"] == {}

    entry2 = json.loads(lines[1])
    assert entry2["raw"] == {"text": "Hello"}


def test_eval_logger_none_is_noop(tmp_path):
    """When eval_logger is None, calling log() on it should not crash — callers guard with 'if self._eval_logger'."""
    # This test confirms the EvalLogger constructor works with no writes if no events logged
    logger = EvalLogger(session_id="empty-456", log_dir=tmp_path)
    log_file = tmp_path / "eval_empty-456.jsonl"
    assert not log_file.exists()  # file not created until first write
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_eval_logger.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `eval_logger` doesn't exist yet.

- [ ] **Step 3: Implement EvalLogger**

```python
# src/governiq/core/eval_logger.py
"""Per-evaluation structured JSONL logger.

Writes one JSON object per line to data/logs/eval_{session_id}.jsonl.
Each entry: {"ts", "task_id", "level", "event", "detail", "raw"}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_LINES = 10_000


class EvalLogger:
    def __init__(self, session_id: str, log_dir: Path) -> None:
        self.session_id = session_id
        self._log_file = log_dir / f"eval_{session_id}.jsonl"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._line_count = 0

    def log(
        self,
        task_id: str,
        level: str,
        event: str,
        detail: str = "",
        raw: dict | None = None,
    ) -> None:
        if self._line_count >= _MAX_LINES:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "level": level,
            "event": event,
            "detail": detail,
            "raw": raw or {},
        }
        try:
            with self._log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._line_count += 1
        except Exception as exc:
            logger.warning("EvalLogger write failed: %s", exc)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_eval_logger.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/core/eval_logger.py tests/test_eval_logger.py
git commit -m "feat: add EvalLogger for per-session JSONL evaluation logging"
```

---

### Task 2: Enrich Stub Schema + Data Directories

**Files:**
- Modify: `src/governiq/candidate/routes.py:382-393`
- Modify: `tests/test_stabilisation.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stabilisation.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
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
    """Stub written by the real /candidate/submit route must contain all enriched schema fields.

    This test exercises the actual candidate_submit handler via FastAPI's TestClient.
    It fails until candidate/routes.py is updated to write the new fields.
    """
    import io
    from fastapi.testclient import TestClient
    import src.governiq.candidate.routes as cand_routes

    # Patch DATA_DIR to use tmp_path so no real disk writes outside tmp
    original_data_dir = cand_routes.DATA_DIR
    original_manifests_dir = cand_routes.MANIFESTS_DIR

    # Create a minimal manifest
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

    try:
        cand_routes.DATA_DIR = tmp_path
        cand_routes.MANIFESTS_DIR = manifests_dir

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
        assert response.status_code == 200
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
        cand_routes.DATA_DIR = original_data_dir
        cand_routes.MANIFESTS_DIR = original_manifests_dir
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_submit_stub_has_all_required_fields -v
```
Expected: FAIL — either `manifest_id`, `submitted_at`, or other new fields are absent from the stub (the current implementation only writes 4 fields).

- [ ] **Step 3: Update `candidate/routes.py` stub write to emit all new fields**

Find the stub write block (lines ~386-393):

```python
# OLD:
with stub_path.open("w") as f:
    json.dump({
        "session_id": session_id,
        "status": "running",
        "candidate_id": candidate_id,
        "assessment_name": manifest.assessment_name,
    }, f)
```

Replace with:

```python
# NEW — import datetime at top of file if not already present
from datetime import datetime, timezone

# ... in the submit handler, after session_id = str(_uuid_mod.uuid4()):
_submitted_at = datetime.now(timezone.utc).isoformat()

# Ensure extra data directories exist
(DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "locks").mkdir(parents=True, exist_ok=True)

with stub_path.open("w") as f:
    json.dump({
        "session_id": session_id,
        "status": "running",
        "candidate_id": candidate_id,
        "manifest_id": manifest.manifest_id,
        "assessment_name": manifest.assessment_name,
        "webhook_url": webhook_url or "",
        "submitted_at": _submitted_at,
        "completed_tasks": [],
        "halt_reason": None,
        "halted_on_task": None,
        "halted_at": None,
        "parent_session_id": None,
        "log_file": f"data/logs/eval_{session_id}.jsonl",
        "error": None,
    }, f)
```

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```
pytest tests/ -v --tb=short -q
```
Expected: same pass/skip counts as before.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/candidate/routes.py tests/test_stabilisation.py
git commit -m "feat: enrich submission stub with full schema fields and create data subdirectories"
```

---

### Task 3: ZIP Storage

**Files:**
- Modify: `src/governiq/candidate/routes.py` (submit handler)
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stabilisation.py`:

```python
def test_zip_cleanup_skips_active_lock(tmp_path):
    """cleanup_old_uploads must NOT delete an upload if a lock file exists for that session."""
    from src.governiq.candidate.routes import cleanup_old_uploads
    import time

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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_zip_cleanup_skips_active_lock -v
```
Expected: `ImportError` — `cleanup_old_uploads` doesn't exist yet.

- [ ] **Step 3: Implement ZIP storage and cleanup in `candidate/routes.py`**

Add near the top of the file (after existing imports):

```python
import shutil
from datetime import datetime, timezone, timedelta
```

Add `cleanup_old_uploads` function:

```python
def cleanup_old_uploads(
    uploads_dir: Path | None = None,
    locks_dir: Path | None = None,
    max_age_days: int = 7,
) -> None:
    """Remove upload directories older than max_age_days, skipping sessions with active locks."""
    uploads_dir = uploads_dir or (DATA_DIR / "uploads")
    locks_dir = locks_dir or (DATA_DIR / "locks")
    if not uploads_dir.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for session_dir in uploads_dir.iterdir():
        if not session_dir.is_dir():
            continue
        lock_file = locks_dir / f"{session_dir.name}.lock"
        if lock_file.exists():
            continue  # Never delete while lock exists
        mtime = datetime.fromtimestamp(session_dir.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            shutil.rmtree(session_dir, ignore_errors=True)
```

In the submit handler, after the stub is written, save the uploaded file. **The raw `content` bytes (already read earlier) must be written, not the parsed dict — this preserves the original ZIP binary for CBM re-analysis.**

```python
# Save bot export for potential re-runs (content is the raw bytes read earlier in the handler)
_upload_dir = DATA_DIR / "uploads" / session_id
_upload_dir.mkdir(parents=True, exist_ok=True)
_filename = (bot_export.filename or "bot_export.json").lower()
_ext = ".zip" if (_filename.endswith(".zip") or content[:4] == b"PK\x03\x04") else ".json"
_upload_path = _upload_dir / f"bot_export{_ext}"
_upload_path.write_bytes(content)  # raw bytes — preserves ZIP binary
```

Note: `content` is the variable holding `await bot_export.read()` from earlier in the submit handler. Use that same variable here.

Also call `cleanup_old_uploads()` at the top of the submit handler (fire-and-forget, best effort):

```python
try:
    cleanup_old_uploads()
except Exception:
    pass
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/candidate/routes.py tests/test_stabilisation.py
git commit -m "feat: save bot export ZIP for re-runs, add cleanup_old_uploads with lock guard"
```

---

### Task 4: Lock File Lifecycle

**Files:**
- Modify: `src/governiq/candidate/routes.py` (`_run_evaluation_background`)
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stabilisation.py`:

```python
def test_lock_created_and_deleted(tmp_path):
    """Lock file must exist during evaluation and be deleted after completion."""
    from src.governiq.candidate.routes import _create_lock, _delete_lock, _is_lock_stale

    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    session_id = "lock-test-999"

    _create_lock(session_id, locks_dir=locks_dir)
    lock_path = locks_dir / f"{session_id}.lock"
    assert lock_path.exists()

    import json
    data = json.loads(lock_path.read_text())
    assert "started_at" in data

    _delete_lock(session_id, locks_dir=locks_dir)
    assert not lock_path.exists()


def test_stale_lock_detection(tmp_path):
    """A lock older than 15 minutes is stale."""
    from src.governiq.candidate.routes import _create_lock, _is_lock_stale
    from datetime import datetime, timezone, timedelta
    import json

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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_lock_created_and_deleted tests/test_stabilisation.py::test_stale_lock_detection -v
```
Expected: `ImportError` — lock helpers don't exist yet.

- [ ] **Step 3: Implement lock helpers in `candidate/routes.py`**

Add these three functions:

```python
def _create_lock(session_id: str, locks_dir: Path | None = None) -> None:
    locks_dir = locks_dir or (DATA_DIR / "locks")
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{session_id}.lock"
    lock_path.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
    }))


def _delete_lock(session_id: str, locks_dir: Path | None = None) -> None:
    locks_dir = locks_dir or (DATA_DIR / "locks")
    lock_path = locks_dir / f"{session_id}.lock"
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def _is_lock_stale(session_id: str, locks_dir: Path | None = None, stale_minutes: int = 15) -> bool:
    """Returns True if no lock exists or the lock is older than stale_minutes."""
    locks_dir = locks_dir or (DATA_DIR / "locks")
    lock_path = locks_dir / f"{session_id}.lock"
    if not lock_path.exists():
        return True
    try:
        data = json.loads(lock_path.read_text())
        started_at = datetime.fromisoformat(data["started_at"])
        age = datetime.now(timezone.utc) - started_at
        return age.total_seconds() > stale_minutes * 60
    except Exception:
        return True  # Corrupt lock = stale
```

Add `import os` at top if not already imported.

In `_run_evaluation_background`, wrap the body with lock create/delete:

```python
async def _run_evaluation_background(...) -> None:
    results_dir = DATA_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stub_path = results_dir / f"scorecard_{session_id}.json"
    _create_lock(session_id)  # ADD THIS
    try:
        # ... existing evaluation code ...
    except Exception as exc:
        # ... existing error handler ...
    finally:
        _delete_lock(session_id)  # ADD THIS — always runs
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/governiq/candidate/routes.py tests/test_stabilisation.py
git commit -m "feat: add lock file lifecycle for evaluation concurrency guard"
```

---

## Phase 1 — Crash Fixes

### Task 5: value_pool Normalisation at Manifest Load Time

**Files:**
- Modify: `src/governiq/core/manifest.py` (or wherever `TaskDefinition` / entity objects are parsed)
- Modify: `tests/test_stabilisation.py`

First identify the manifest loader:

```bash
grep -n "value_pool" src/governiq/core/manifest.py
```

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stabilisation.py`:

```python
def test_value_pool_dict_normalised_at_load():
    """A value_pool authored as a JSON object must be converted to a list at load time."""
    from src.governiq.core.manifest import normalise_value_pools

    task_data = {
        "task_id": "t1",
        "required_entities": [
            {"entity_key": "city", "value_pool": {"0": "London", "1": "Paris", "2": "Rome"}},
            {"entity_key": "date", "value_pool": ["2026-01-01", "2026-02-01"]},  # already a list
        ],
    }
    normalise_value_pools(task_data)

    entities = task_data["required_entities"]
    assert isinstance(entities[0]["value_pool"], list)
    assert set(entities[0]["value_pool"]) == {"London", "Paris", "Rome"}
    assert entities[1]["value_pool"] == ["2026-01-01", "2026-02-01"]  # unchanged
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_value_pool_dict_normalised_at_load -v
```
Expected: `ImportError` — `normalise_value_pools` doesn't exist yet.

- [ ] **Step 3: Add `normalise_value_pools` to `manifest.py` and call it during manifest parsing**

In `src/governiq/core/manifest.py`, add:

```python
import logging as _log
_mlog = logging.getLogger(__name__)


def normalise_value_pools(task_data: dict) -> None:
    """Convert any dict-typed value_pool to a list in-place. Warns if conversion needed."""
    for entity in task_data.get("required_entities", []):
        vp = entity.get("value_pool")
        if isinstance(vp, dict):
            _mlog.warning(
                "MD-VPOOL: task '%s' entity '%s' value_pool is a dict — auto-converted to list. Fix manifest.",
                task_data.get("task_id", "?"),
                entity.get("entity_key", "?"),
            )
            entity["value_pool"] = list(vp.values())
```

Then find where tasks are loaded from JSON (look for `TaskDefinition` construction or wherever `tasks` list is iterated) and call `normalise_value_pools(task_data)` on each task dict before constructing the object.

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py::test_value_pool_dict_normalised_at_load -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/governiq/core/manifest.py tests/test_stabilisation.py
git commit -m "fix: normalise dict value_pool to list at manifest load time (fixes KeyError: 2 crash)"
```

---

### Task 6: Message Normaliser

**Files:**
- Create: `src/governiq/webhook/message_normaliser.py`
- Create: `tests/test_message_normaliser.py`
- Modify: `src/governiq/webhook/driver.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_message_normaliser.py
import pytest
from src.governiq.webhook.message_normaliser import extract_text, normalise_messages


def test_plain_string():
    assert extract_text("Hello world") == "Hello world"


def test_dict_with_val():
    assert extract_text({"val": "Hello"}) == "Hello"


def test_dict_with_text():
    assert extract_text({"text": "Hi there"}) == "Hi there"


def test_dict_with_payload_text():
    assert extract_text({"payload": {"text": "Payload text"}}) == "Payload text"


def test_template_message():
    result = extract_text({"type": "template", "payload": {"some": "data"}})
    assert result == "[template message]"


def test_unknown_dict_falls_back_to_str():
    result = extract_text({"unknown_key": "value"})
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalise_messages_mixed():
    messages = [
        "Hello",
        {"val": "How can I help?"},
        {"type": "template", "payload": {}},
    ]
    texts, raws = normalise_messages(messages)
    assert texts == ["Hello", "How can I help?", "[template message]"]
    assert raws[0] == "Hello"
    assert raws[1] == {"val": "How can I help?"}
    assert raws[2] == {"type": "template", "payload": {}}


def test_normalise_messages_empty():
    texts, raws = normalise_messages([])
    assert texts == []
    assert raws == []
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_message_normaliser.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement the normaliser**

```python
# src/governiq/webhook/message_normaliser.py
"""Safe text extraction from Kore.ai webhook response message objects.

Kore.ai can return messages as plain strings or structured dicts.
This module normalises both into displayable text while preserving raw structure.
"""
from __future__ import annotations


def extract_text(message: str | dict) -> str:
    """Extract displayable text from a single Kore.ai message object."""
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return str(message)

    # Direct text fields
    if "val" in message:
        return str(message["val"])
    if "text" in message and isinstance(message["text"], str):
        return message["text"]

    # Nested payload
    payload = message.get("payload")
    if isinstance(payload, dict):
        if "text" in payload:
            return str(payload["text"])

    # Template / rich card — no plain text available
    if message.get("type") == "template":
        return "[template message]"

    # Fallback: stringify the whole thing
    return str(message)


def normalise_messages(messages: list) -> tuple[list[str], list]:
    """Normalise a list of Kore.ai messages.

    Returns:
        texts: list of plain text strings (for LLM classification and display)
        raws: original message objects (for evidence storage)
    """
    texts = [extract_text(m) for m in messages]
    return texts, list(messages)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_message_normaliser.py -v
```
Expected: all PASS.

- [ ] **Step 5: Wire into `driver.py`**

Find in `src/governiq/webhook/driver.py` all places where bot response messages are joined or concatenated as strings. Add at the top of the file:

```python
from .message_normaliser import normalise_messages
```

Replace any `", ".join(messages)` or similar with:

```python
_texts, _raws = normalise_messages(messages)
bot_text = " ".join(_texts)
```

Run the full test suite to confirm no regressions:

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/webhook/message_normaliser.py tests/test_message_normaliser.py src/governiq/webhook/driver.py
git commit -m "fix: add message normaliser to handle dict bot responses (fixes sequence item crash)"
```

---

### Task 7: Template Guards

**Files:**
- Modify: `src/governiq/templates/candidate_history.html`
- Identify and modify the admin submission list template
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stabilisation.py`:

```python
def test_template_guard_error_stub():
    """Rendering candidate_history with an error stub must not raise UndefinedError."""
    from jinja2 import Environment, FileSystemLoader, Undefined
    from pathlib import Path

    template_dir = Path("src/governiq/templates")
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=Undefined,  # strict — raises on missing
    )

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
            request=None,
            portal="candidate",
            submissions=[error_stub],
        )
        # If we get here, the template rendered without crashing — success
        assert "err-stub-1" in rendered or "error" in rendered.lower()
    except Exception as e:
        pytest.fail(f"Template raised an exception for error stub: {e}")
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_template_guard_error_stub -v
```
Expected: FAIL with `jinja2.exceptions.UndefinedError` or `TypeError` — the template accesses `s.overall_score` unconditionally.

- [ ] **Step 3: Locate the exact template files**

```bash
grep -rn "overall_score" src/governiq/templates/
```

Note every template file and line that accesses `overall_score`, `task_scores`, or `has_critical_failures` directly without a guard.

- [ ] **Step 4: Fix `candidate_history.html`**

Find the line (approx line 36):
```html
<strong class="{% if s.overall_score >= 0.7 %}text-pass{% else %}text-fail{% endif %}">
```

Replace with:
```html
{% if s.overall_score is defined and s.overall_score is not none %}
<strong class="{% if s.overall_score >= 0.7 %}text-pass{% else %}text-fail{% endif %}">
  {{ (s.overall_score * 100) | round(1) }}%
</strong>
{% else %}
<span class="badge badge-{{ s.status | default('error') }}">{{ s.status | default('error') | upper }}</span>
{% endif %}
```

- [ ] **Step 5: Apply same guard to the admin submission list template**

For every `s.overall_score` access in admin templates, wrap with the same `{% if s.overall_score is defined and s.overall_score is not none %}` guard.

- [ ] **Step 6: Run the test**

```
pytest tests/test_stabilisation.py::test_template_guard_error_stub -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/governiq/templates/ tests/test_stabilisation.py
git commit -m "fix: add Jinja2 template guards for overall_score on incomplete stubs (fixes history 500)"
```

---

### Task 8: CSS Fixes — Dropdown Visibility + API Key Show/Hide

**Files:**
- Modify: `src/governiq/templates/base.html`
- Identify and modify admin settings template

- [ ] **Step 1: Fix dropdown white-on-white**

In `src/governiq/templates/base.html`, find the `<style>` block or linked CSS. Add:

```css
/* Fix: select elements invisible on some browsers due to white-on-white */
select,
select option {
    color: #1e293b;
    background-color: #ffffff;
}
```

- [ ] **Step 2: Audit all templates for `<select>` elements**

```bash
grep -rn "<select" src/governiq/templates/
```

Confirm the CSS above is in `base.html` which is extended by all templates. If any template overrides the colour, remove the override.

- [ ] **Step 3: Add API key show/hide toggle to the admin settings template**

Find all `<input type="password"` or API-key inputs in the settings template. Wrap each with:

```html
<div class="input-with-toggle">
  <input type="password" id="api_key" name="api_key" value="{{ config.api_key or '' }}" class="form-input" />
  <button type="button" class="show-hide-btn" onclick="toggleVisibility('api_key', this)" aria-label="Show/hide key">
    <span class="icon-eye">👁</span>
  </button>
</div>
```

Add to base.html `<script>` section:

```javascript
function toggleVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  if (input.type === 'password') {
    input.type = 'text';
    btn.setAttribute('aria-label', 'Hide key');
    btn.querySelector('.icon-eye').textContent = '🙈';
  } else {
    input.type = 'password';
    btn.setAttribute('aria-label', 'Show key');
    btn.querySelector('.icon-eye').textContent = '👁';
  }
}
```

- [ ] **Step 4: Test manually**

Start server, navigate to `/admin/settings`. Confirm dropdowns show text, API key field has toggle button and it works.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/templates/
git commit -m "fix: resolve white-on-white dropdown text, add API key show/hide toggle"
```

---

### Task 9: validate_manifest_data

**Files:**
- Modify: `src/governiq/admin/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_stabilisation.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_validate_manifest_data_valid tests/test_stabilisation.py::test_validate_manifest_data_bad_threshold tests/test_stabilisation.py::test_validate_manifest_data_warnings_only -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement `validate_manifest_data` in `admin/routes.py`**

Add before `_save_manifest`:

```python
def validate_manifest_data(data: dict) -> dict:
    """Pre-flight validation of a raw manifest dict.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}.
    Errors block save. Warnings are shown but do not block.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required fields
    for field in ("manifest_id", "tasks", "scoring_config"):
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    # pass_threshold range
    sc = data.get("scoring_config", {})
    pt = sc.get("pass_threshold")
    if pt is not None and not (0.5 <= pt <= 1.0):
        errors.append(f"pass_threshold must be between 0.5 and 1.0 (got {pt})")

    # Weight sum
    if sc:
        w_sum = (
            sc.get("webhook_functional_weight", 0)
            + sc.get("compliance_weight", 0)
            + sc.get("faq_weight", 0)
        )
        if abs(w_sum - 1.0) > 0.01:
            warnings.append(
                f"scoring_config weights sum to {w_sum:.3f} instead of 1.0 — will be normalised at evaluation time"
            )

    # value_pool type check
    for task in data.get("tasks", []):
        for entity in task.get("required_entities", []):
            vp = entity.get("value_pool")
            if isinstance(vp, dict):
                warnings.append(
                    f"Task '{task.get('task_id')}' entity '{entity.get('entity_key')}': "
                    f"value_pool is a JSON object — convert to array in manifest editor"
                )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
```

In `_save_manifest`, call `validate_manifest_data` before writing:

```python
def _save_manifest(data: dict[str, Any]) -> Path:
    result = validate_manifest_data(data)
    if not result["valid"]:
        raise ValueError(f"Manifest validation failed: {result['errors']}")
    # ... existing save logic ...
```

Update the manifest save routes to catch `ValueError` and return 400 with error details, and pass warnings to the redirect URL.

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py -v -k "validate"
```
Expected: 3 PASSED.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/admin/routes.py tests/test_stabilisation.py
git commit -m "feat: add validate_manifest_data with pre-flight checks at manifest save time"
```

---

## Phase 2 — Engine Stability

### Task 10: EvaluationHaltedError

**Files:**
- Create: `src/governiq/core/exceptions.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_evaluation_halted_error_attributes -v
```

- [ ] **Step 3: Implement**

```python
# src/governiq/core/exceptions.py
"""Domain exceptions for the EvalAutomaton engine."""


class EvaluationHaltedError(Exception):
    """Raised when an evaluation must stop due to an unrecoverable external error.

    Attributes:
        reason: Human-readable description of why the evaluation halted.
        task_id: The task that was running when the error occurred.
        retriable: True if retrying after fixing the issue may succeed (e.g. rate limit).
                   False if the error requires a config fix (e.g. invalid API key).
    """

    def __init__(self, reason: str, task_id: str, retriable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.task_id = task_id
        self.retriable = retriable
```

- [ ] **Step 4: Run test**

```
pytest tests/test_stabilisation.py::test_evaluation_halted_error_attributes -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/core/exceptions.py tests/test_stabilisation.py
git commit -m "feat: add EvaluationHaltedError exception for controlled evaluation halt"
```

---

### Task 11: Retry-Once Then Halt in `driver.py`

**Files:**
- Modify: `src/governiq/webhook/driver.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
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

        result = asyncio.run(
            driver._llm_call("sys", "user", task_id="task1")
        )
        assert result == "Hello"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_halt_on_429_after_retry tests/test_stabilisation.py::test_retry_success_on_first_429 -v
```
Expected: failures (current `_llm_call` has no `task_id` param and no retry logic).

- [ ] **Step 3: Update `_llm_call` in `driver.py`**

Change the signature and body of `_llm_call` (currently lines 74-118):

```python
async def _llm_call(
    self, system_prompt: str, user_prompt: str, task_id: str = "unknown"
) -> str | None:
    """Make an LLM API call with one retry. Raises EvaluationHaltedError on persistent failure."""
    from ..core.exceptions import EvaluationHaltedError

    async def _attempt() -> str | None:
        client = await self._get_client()
        if self.api_format == "anthropic":
            response = await client.post(
                "/messages",
                json={
                    "model": self.model,
                    "max_tokens": 256,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": self.temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            if content and isinstance(content, list):
                return content[0].get("text", "").strip()
            return None
        else:
            response = await client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": 256,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

    if not self.api_key and self.api_format == "anthropic":
        return None

    # --- First attempt ---
    try:
        return await _attempt()
    except Exception as first_exc:
        err_str = str(first_exc)
        # 401 = bad key — do not retry, halt immediately
        if "401" in err_str:
            raise EvaluationHaltedError(
                reason=f"LLM authentication failed: {err_str}",
                task_id=task_id,
                retriable=False,
            )
        logger.warning("LLM call failed on first attempt, retrying in 8s: %s", first_exc)

    # --- One retry after 8 seconds ---
    await asyncio.sleep(8)
    try:
        return await _attempt()
    except Exception as second_exc:
        raise EvaluationHaltedError(
            reason=f"LLM call failed after retry: {second_exc}",
            task_id=task_id,
            retriable=True,
        )
```

Update all callers of `_llm_call` in `driver.py` to pass `task_id=` where available.

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py::test_halt_on_429_after_retry tests/test_stabilisation.py::test_retry_success_on_first_429 -v
```
Expected: both PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/webhook/driver.py tests/test_stabilisation.py
git commit -m "feat: add retry-once then halt behavior to LLM calls (fixes silent 429 fallback)"
```

---

### Task 12: Halt Handler in Engine + EvalLogger Wiring

**Files:**
- Modify: `src/governiq/core/engine.py`
- Modify: `src/governiq/candidate/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_halt_writes_checkpoint -v
```
Expected: FAIL — `_run_evaluation_background` has no `EvaluationHaltedError` handler yet (it falls through to the broad `except Exception` and writes `status="error"`, not `"halted"`).

- [ ] **Step 3: Add EvalLogger to `EvaluationEngine.__init__`**

In `src/governiq/core/engine.py`, modify `__init__` (lines 58-90):

```python
from .eval_logger import EvalLogger  # add import

def __init__(
    self,
    manifest: Manifest,
    llm_api_key: str = "",
    llm_model: str = "claude-haiku-4-5-20251001",
    llm_base_url: str = "https://api.anthropic.com/v1",
    llm_api_format: str = "anthropic",
    persist_dir: str = "./data",
    kore_bearer_token: str = "",
    kore_credentials: KoreCredentials | None = None,
    eval_logger: EvalLogger | None = None,   # ADD THIS
):
    # ... existing assignments ...
    self._eval_logger = eval_logger          # ADD THIS

    self.driver = LLMConversationDriver(
        api_key=llm_api_key,
        model=llm_model,
        base_url=llm_base_url,
        api_format=llm_api_format,
        eval_logger=eval_logger,             # ADD THIS — pass down to driver
    )
    # ... rest of __init__ unchanged ...
```

Add `eval_logger: EvalLogger | None = None` parameter to `LLMConversationDriver.__init__` as well (store as `self._eval_logger`).

- [ ] **Step 4: Add halt catch to `_run_webhook_pipeline` in `engine.py`**

Find `_run_webhook_pipeline` and wrap the task execution loop:

```python
from .exceptions import EvaluationHaltedError  # add import
from datetime import datetime, timezone

# Inside _run_webhook_pipeline, wrap the task loop:
try:
    # ... existing task execution loop ...
    if self._eval_logger:
        self._eval_logger.log(task_id=task.task_id, level="info", event="task_start",
                              detail=f"Starting task {task.task_id} ({task.pattern})")
    # ... run task ...
    if self._eval_logger:
        self._eval_logger.log(task_id=task.task_id, level="info", event="task_complete",
                              detail=f"Score: {task_score.combined_score:.2f}")
except EvaluationHaltedError as halt_err:
    if self._eval_logger:
        self._eval_logger.log(task_id=halt_err.task_id, level="error",
                              event="evaluation_halted", detail=halt_err.reason)
    context.save()  # checkpoint
    raise  # propagate to _run_evaluation_background
```

- [ ] **Step 5: Add `EvaluationHaltedError` handler in `candidate/routes.py`**

In `_run_evaluation_background`, add a specific handler BEFORE the broad `except Exception`:

```python
from ..core.exceptions import EvaluationHaltedError  # add import

# In _run_evaluation_background:
try:
    # ... existing engine code ...
except EvaluationHaltedError as halt_err:
    logger.warning("Evaluation halted for session %s: %s", session_id, halt_err.reason)
    # Read existing stub and update it
    try:
        existing = json.loads(stub_path.read_text()) if stub_path.exists() else {}
    except Exception:
        existing = {}
    existing.update({
        "status": "halted",
        "halt_reason": halt_err.reason,
        "halted_on_task": halt_err.task_id,
        "halted_at": datetime.now(timezone.utc).isoformat(),
    })
    with stub_path.open("w") as f:
        json.dump(existing, f, indent=2)
except Exception as exc:
    # ... existing broad handler unchanged ...
finally:
    _delete_lock(session_id)
```

In `_run_evaluation_background`, create the `EvalLogger` and pass it to the engine:

```python
from ..core.eval_logger import EvalLogger
from pathlib import Path

_log_dir = DATA_DIR / "logs"
_eval_logger = EvalLogger(session_id=session_id, log_dir=_log_dir)

engine = EvaluationEngine(
    manifest=manifest,
    # ... existing params ...
    eval_logger=_eval_logger,   # ADD THIS
)
```

- [ ] **Step 6: Run full test suite**

```
pytest tests/ -q
```
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/governiq/core/engine.py src/governiq/webhook/driver.py src/governiq/candidate/routes.py
git commit -m "feat: wire EvalLogger into engine + driver, add halt handler that checkpoints on LLM failure"
```

---

## Phase 3 — Admin Control Surface

### Task 13: Show All Submissions + `_enrich_submission`

**Files:**
- Modify: `src/governiq/admin/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_admin_shows_all_statuses(tmp_path):
    """_load_all_evaluations must return records of every status."""
    import json
    from pathlib import Path

    # We'll patch DATA_DIR to use tmp_path
    statuses = ["completed", "running", "halted", "error"]
    results = tmp_path / "results"
    results.mkdir()
    for i, s in enumerate(statuses):
        path = results / f"scorecard_stub-{i}.json"
        path.write_text(json.dumps({"session_id": f"stub-{i}", "status": s,
                                     "overall_score": 0.8 if s == "completed" else None}))

    # Import and patch
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
    from pathlib import Path
    import src.governiq.admin.routes as admin_routes

    session_id = "enrich-test"
    # Create a valid RuntimeContext
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

    # Empty context = no completed_tasks = cannot resume meaningfully
    assert enriched["can_resume"] is False
```

- [ ] **Step 2: Run to confirm failures**

```
pytest tests/test_stabilisation.py -v -k "admin_shows or enrich"
```

- [ ] **Step 3: Update `_load_all_evaluations` — remove status filter**

In `admin/routes.py` lines 36-51, remove the `if data.get("status") in ("running", "error"): continue` block:

```python
def _load_all_evaluations() -> list[dict[str, Any]]:
    results_dir = DATA_DIR / "results"
    if not results_dir.exists():
        return []
    evals = []
    for f in sorted(results_dir.glob("scorecard_*.json"), reverse=True):
        try:
            with f.open("r") as fh:
                data = json.load(fh)
            evals.append(_enrich_submission(data))
        except Exception:
            pass
    return evals
```

- [ ] **Step 4: Add `_enrich_submission` helper**

```python
def _enrich_submission(data: dict[str, Any]) -> dict[str, Any]:
    """Add computed display fields to a raw scorecard/stub dict."""
    from datetime import datetime, timezone, timedelta

    session_id = data.get("session_id", "")
    status = data.get("status", "error")

    # Stale detection — running submissions older than 15 minutes
    display_status = status
    if status == "running":
        submitted_at_str = data.get("submitted_at")
        if not submitted_at_str:
            display_status = "stale"  # Legacy stub without submitted_at
        else:
            try:
                submitted_at = datetime.fromisoformat(submitted_at_str)
                age = datetime.now(timezone.utc) - submitted_at
                if age > timedelta(minutes=15):
                    display_status = "stale"
            except Exception:
                display_status = "stale"

    # Lock check
    lock_path = DATA_DIR / "locks" / f"{session_id}.lock"
    has_active_lock = lock_path.exists() and not _is_lock_stale_admin(session_id)

    # ZIP availability
    upload_dir = DATA_DIR / "uploads" / session_id
    zip_available = upload_dir.exists() and any(upload_dir.iterdir())

    # Resume check — RuntimeContext must exist, be valid JSON, and have session_id
    can_resume = False
    if status in ("halted", "error") and not has_active_lock:
        ctx_path = DATA_DIR / "runtime_contexts" / f"context_{session_id}.json"
        if ctx_path.exists():
            try:
                ctx_data = json.loads(ctx_path.read_text())
                # Must have a session_id key to be considered a valid context
                can_resume = bool(ctx_data.get("session_id"))
            except Exception:
                pass

    return {
        **data,
        # Safe defaults for fields that may be absent in old stubs
        "overall_score": data.get("overall_score"),
        "candidate_id": data.get("candidate_id", "unknown"),
        "manifest_id": data.get("manifest_id", "unknown"),
        "assessment_name": data.get("assessment_name", "Unknown Assessment"),
        "submitted_at": data.get("submitted_at"),
        "halt_reason": data.get("halt_reason"),
        # Computed display fields
        "display_status": display_status,
        "has_active_lock": has_active_lock,
        "zip_available": zip_available,
        "can_resume": can_resume,
        "can_start_fresh": status not in ("running",) and not has_active_lock,
    }


def _is_lock_stale_admin(session_id: str, stale_minutes: int = 15) -> bool:
    """Admin-side stale lock check (mirrors candidate/routes.py version)."""
    from datetime import datetime, timezone, timedelta
    lock_path = DATA_DIR / "locks" / f"{session_id}.lock"
    if not lock_path.exists():
        return True
    try:
        data = json.loads(lock_path.read_text())
        started_at = datetime.fromisoformat(data["started_at"])
        return (datetime.now(timezone.utc) - started_at) > timedelta(minutes=stale_minutes)
    except Exception:
        return True
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_stabilisation.py -v -k "admin_shows or enrich"
```
Expected: all PASS.

- [ ] **Step 6: Run full suite**

```
pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add src/governiq/admin/routes.py tests/test_stabilisation.py
git commit -m "feat: show all submission statuses in admin, add _enrich_submission with re-run metadata"
```

---

### Task 14: Admin Submission List Template — Status Badges + Re-run Buttons

**Files:**
- Identify admin submissions template: `grep -rn "scorecard\|submission" src/governiq/templates/ --include="*.html" -l`
- Modify that template

- [ ] **Step 1: Locate the admin submissions template**

```bash
grep -rn "submission\|scorecard\|overall_score" src/governiq/templates/ --include="*.html" -l
```

Open the file and find where submissions are iterated.

- [ ] **Step 2: Add status badge display**

In the submissions table/list, replace or augment the status column:

```html
{% set badge_class = {
  'completed': 'badge-success',
  'running':   'badge-info',
  'halted':    'badge-warning',
  'error':     'badge-danger',
  'stale':     'badge-secondary',
} %}

<span class="badge {{ badge_class.get(s.display_status, 'badge-secondary') }}"
      {% if s.display_status == 'halted' and s.halt_reason %}
      title="{{ s.halt_reason }}"
      {% endif %}>
  {% if s.display_status == 'running' %}<span class="spinner"></span>{% endif %}
  {{ s.display_status | upper }}
</span>
```

- [ ] **Step 3: Add re-run buttons**

In each row, add a controls column:

```html
<td class="controls-col">
  {% if not s.has_active_lock %}
    {% if s.can_start_fresh %}
      {% if s.zip_available %}
        <form method="POST" action="/admin/evaluation/{{ s.session_id }}/restart" style="display:inline">
          <input type="hidden" name="mode" value="fresh">
          <button type="submit" class="btn btn-sm btn-outline">Start Fresh</button>
        </form>
      {% else %}
        <button class="btn btn-sm btn-outline" disabled title="Re-upload required">Start Fresh</button>
      {% endif %}
    {% endif %}
    {% if s.can_resume %}
      <form method="POST" action="/admin/evaluation/{{ s.session_id }}/restart" style="display:inline">
        <input type="hidden" name="mode" value="resume">
        <button type="submit" class="btn btn-sm btn-primary">Resume</button>
      </form>
    {% endif %}
  {% else %}
    <button class="btn btn-sm btn-outline" disabled title="Evaluation is currently running">Running…</button>
  {% endif %}
</td>
```

- [ ] **Step 4: Group re-runs under parent**

If `s.parent_session_id` is set, render the row as an indented sub-row:

```html
<tr class="{% if s.parent_session_id %}re-run-row{% endif %}">
  {% if s.parent_session_id %}
  <td colspan="1" class="re-run-indent">↳ Re-run</td>
  {% endif %}
  ...
</tr>
```

Add CSS:
```css
.re-run-row { background: #f8fafc; }
.re-run-indent { padding-left: 2rem; color: #64748b; font-size: 0.85em; }
```

- [ ] **Step 5: Test manually**

Start the server. Navigate to the admin dashboard. Confirm:
- All 4 status types render with correct badge colours
- Halted submissions show amber badge with reason tooltip
- Start Fresh / Resume buttons appear correctly
- Running submissions show a spinner

- [ ] **Step 6: Commit**

```bash
git add src/governiq/templates/
git commit -m "feat: admin submission list shows all statuses with badges and re-run controls"
```

---

### Task 15: Restart Endpoint

**Files:**
- Modify: `src/governiq/admin/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Implement the restart endpoint in `admin/routes.py`**

```python
@router.post("/evaluation/{session_id}/restart")
async def restart_evaluation(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
    mode: str = Form(...),
):
    """Restart an evaluation — mode='fresh' (new session) or mode='resume' (from checkpoint)."""
    import uuid

    results_dir = DATA_DIR / "results"
    stub_path = results_dir / f"scorecard_{session_id}.json"

    # Load original stub
    if not stub_path.exists():
        return JSONResponse({"error": "Submission not found"}, status_code=404)
    try:
        original_stub = json.loads(stub_path.read_text())
    except Exception:
        return JSONResponse({"error": "Cannot read submission data"}, status_code=500)

    # Guard: active lock
    if not _is_lock_stale_admin(session_id):
        return JSONResponse(
            {"error": "Evaluation is currently running. Please wait before re-running."},
            status_code=409,
        )

    if mode == "fresh":
        # Guard: ZIP must exist
        upload_dir = DATA_DIR / "uploads" / session_id
        if not upload_dir.exists() or not any(upload_dir.iterdir()):
            return JSONResponse(
                {"error": "Original upload not found — re-upload required via candidate portal"},
                status_code=400,
            )
        # Create new session
        new_session_id = str(uuid.uuid4())
        new_stub_path = results_dir / f"scorecard_{new_session_id}.json"
        new_stub = {
            **original_stub,
            "session_id": new_session_id,
            "status": "running",
            "completed_tasks": [],
            "halt_reason": None,
            "halted_on_task": None,
            "halted_at": None,
            "parent_session_id": session_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "log_file": f"data/logs/eval_{new_session_id}.jsonl",
            "error": None,
        }
        with new_stub_path.open("w") as f:
            json.dump(new_stub, f, indent=2)

        # Load manifest for re-launch
        manifest_id = original_stub.get("manifest_id", "")
        manifest_obj = None
        for mf in MANIFESTS_DIR.glob("*.json"):
            try:
                mdata = json.loads(mf.read_text())
                if mdata.get("manifest_id") == manifest_id:
                    from ..core.manifest import Manifest
                    manifest_obj = Manifest(**mdata)
                    break
            except Exception:
                continue
        if manifest_obj is None:
            return JSONResponse(
                {"error": f"Manifest '{manifest_id}' not found — cannot re-run"},
                status_code=422,
            )

        # Re-load LLM config and launch background evaluation
        from ..core.llm_config import load_llm_config
        llm_config = load_llm_config()

        # Re-parse the saved bot export — must handle both JSON and ZIP files
        # (Task 3 saves raw bytes; detect by extension or magic bytes)
        import io as _io_mod
        import zipfile as _zf_mod
        _upload_files = list(upload_dir.iterdir())
        _upload_file = _upload_files[0]  # Only one file per session
        _raw_bytes = _upload_file.read_bytes()
        if _upload_file.suffix == ".zip" or _raw_bytes[:4] == b"PK\x03\x04":
            with _zf_mod.ZipFile(_io_mod.BytesIO(_raw_bytes)) as zf:
                _json_files = [
                    n for n in zf.namelist()
                    if n.endswith(".json") and not n.startswith("__MACOSX")
                ]
                if not _json_files:
                    return JSONResponse({"error": "No JSON file found in saved ZIP"}, status_code=422)
                _json_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                with zf.open(_json_files[0]) as jf:
                    _bot_export_data = json.loads(jf.read())
        else:
            _bot_export_data = json.loads(_raw_bytes)

        background_tasks.add_task(
            _run_evaluation_background,
            session_id=new_session_id,
            manifest=manifest_obj,
            bot_export_data=_bot_export_data,
            candidate_id=original_stub.get("candidate_id", ""),
            webhook_url=original_stub.get("webhook_url", ""),
            kore_creds=None,  # Admin re-runs use saved eval config; creds not re-entered
            llm_config=llm_config,
            kore_bearer_token="",
            plag_report=None,
        )
        return RedirectResponse(
            url=f"/admin/?restarted={new_session_id}", status_code=303
        )

    elif mode == "resume":
        ctx_path = DATA_DIR / "runtime_contexts" / f"context_{session_id}.json"
        if not ctx_path.exists():
            return JSONResponse(
                {"error": "Checkpoint not found — use Start Fresh instead"},
                status_code=400,
            )
        try:
            ctx_data = json.loads(ctx_path.read_text())
            if not ctx_data.get("session_id"):
                raise ValueError("Empty context")
        except Exception:
            return JSONResponse(
                {"error": "Checkpoint is corrupt — use Start Fresh instead"},
                status_code=400,
            )

        new_session_id = str(uuid.uuid4())
        new_stub_path = results_dir / f"scorecard_{new_session_id}.json"
        new_stub = {
            **original_stub,
            "session_id": new_session_id,
            "status": "running",
            "completed_tasks": original_stub.get("completed_tasks", []),
            "halt_reason": None,
            "halted_on_task": None,
            "halted_at": None,
            "parent_session_id": session_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "log_file": f"data/logs/eval_{new_session_id}.jsonl",
            "error": None,
        }
        with new_stub_path.open("w") as f:
            json.dump(new_stub, f, indent=2)

        # Load manifest and resume from checkpoint using source_session_id
        manifest_id = original_stub.get("manifest_id", "")
        manifest_obj = None
        for mf in MANIFESTS_DIR.glob("*.json"):
            try:
                mdata = json.loads(mf.read_text())
                if mdata.get("manifest_id") == manifest_id:
                    from ..core.manifest import Manifest
                    manifest_obj = Manifest(**mdata)
                    break
            except Exception:
                continue
        if manifest_obj is None:
            return JSONResponse(
                {"error": f"Manifest '{manifest_id}' not found — cannot resume"},
                status_code=422,
            )

        from ..core.llm_config import load_llm_config
        llm_config = load_llm_config()

        async def _do_resume():
            """Background task: resume from checkpoint using source_session_id."""
            from ..core.engine import EvaluationEngine
            from ..core.eval_logger import EvalLogger
            _log_dir = DATA_DIR / "logs"
            _eval_logger = EvalLogger(session_id=new_session_id, log_dir=_log_dir)
            engine = EvaluationEngine(
                manifest=manifest_obj,
                llm_api_key=llm_config.api_key,
                llm_model=llm_config.model,
                llm_base_url=llm_config.base_url,
                llm_api_format=llm_config.api_format,
                eval_logger=_eval_logger,
            )
            try:
                scorecard = await engine.resume_evaluation(
                    source_session_id=session_id,
                    new_session_id=new_session_id,
                )
                with new_stub_path.open("w") as f:
                    json.dump(scorecard.to_dict(), f, indent=2)
            except Exception as exc:
                logger.exception("Resume failed for new session %s", new_session_id)
                existing = json.loads(new_stub_path.read_text()) if new_stub_path.exists() else {}
                existing.update({"status": "error", "error": str(exc)})
                with new_stub_path.open("w") as f:
                    json.dump(existing, f, indent=2)

        background_tasks.add_task(_do_resume)
        return RedirectResponse(
            url=f"/admin/?restarted={new_session_id}", status_code=303
        )

    return JSONResponse({"error": f"Unknown mode: {mode}"}, status_code=400)
```

Also update `engine.resume_evaluation` signature to accept `source_session_id` and `new_session_id`:

In `engine.py`, find `resume_evaluation(self, session_id: str)` and change to:

```python
async def resume_evaluation(
    self,
    source_session_id: str,
    new_session_id: str,
    ...
) -> Scorecard:
    # Load RuntimeContext from source
    context = RuntimeContext.load(self.persist_dir / "runtime_contexts" / f"context_{source_session_id}.json")
    context.session_id = new_session_id  # redirect output to new session
    # ... rest of resume logic writes under new_session_id ...
```

Update the existing `/api/v1/evaluations/{session_id}/resume` endpoint in `api/routes.py` to accept both IDs.

- [ ] **Step 3: Run tests**

```
pytest tests/test_stabilisation.py::test_restart_blocked_by_active_lock -v
```
Expected: PASS.

- [ ] **Step 4: Run full suite**

```
pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/governiq/admin/routes.py src/governiq/core/engine.py src/governiq/api/routes.py tests/test_stabilisation.py
git commit -m "feat: add admin restart endpoint with fresh/resume modes and lock guard"
```

---

### Task 16: Inline API Key Verification

**Files:**
- Modify: `src/governiq/admin/routes.py` (`save_llm_settings`)
- Modify: admin settings template

- [ ] **Step 1: Identify the settings save endpoint**

```bash
grep -n "save_llm_settings\|llm-config\|llm_config" src/governiq/admin/routes.py | head -20
```

- [ ] **Step 2: Add inline probe after save**

In `save_llm_settings` (or `save_llm_config`), after saving the config, call `_check_ai_model()`:

```python
# After saving config:
probe_result = _check_ai_model()  # uses the freshly saved config
verified = "1" if probe_result["status"] == "ok" else "0"
reason = probe_result.get("message", "")

return RedirectResponse(
    url=f"/admin/settings?saved=1&verified={verified}&reason={reason}",
    status_code=303,
)
```

Note: `_check_ai_model` is defined in `api/routes.py`. Extract it to a shared location or import it. The cleanest approach: move `_check_ai_model` to a `src/governiq/core/health.py` helper so both `api/routes.py` and `admin/routes.py` can import it.

- [ ] **Step 3: Render verification result in settings template**

In the admin settings template, add above the form:

```html
{% if request.query_params.get('verified') == '1' %}
<div class="alert alert-success">
  API key verified — provider connected successfully.
</div>
{% elif request.query_params.get('verified') == '0' %}
<div class="alert alert-danger">
  API key could not be verified: {{ request.query_params.get('reason', 'Unknown error') }}
</div>
{% endif %}
```

- [ ] **Step 4: Test manually**

Navigate to `/admin/settings`, enter a valid Gemini API key, save. Should see green "API key verified" banner. Enter an invalid key, save. Should see red banner.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/admin/routes.py src/governiq/templates/
git commit -m "feat: inline API key verification result shown on settings save"
```

---

## Phase 4 — Live Log Panel

### Task 17: Log Streaming Endpoint

**Files:**
- Modify: `src/governiq/api/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_log_endpoint_offset(tmp_path):
    """GET /api/v1/logs/{id}?offset=N returns only entries after offset."""
    import json
    from pathlib import Path

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

    # Simulate the read_log_entries function
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_log_endpoint_offset tests/test_stabilisation.py::test_log_endpoint_done_when_terminal -v
```

- [ ] **Step 3: Implement `read_log_entries` and the endpoint in `api/routes.py`**

```python
def read_log_entries(
    session_id: str,
    offset: int = 0,
    logs_dir: Path | None = None,
) -> dict:
    """Read log entries from the JSONL file starting at offset."""
    logs_dir = logs_dir or (DATA_DIR / "logs")
    log_file = logs_dir / f"eval_{session_id}.jsonl"

    entries = []
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            lines = [l for l in lines if l.strip()]
            for line in lines[offset:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass

    next_offset = offset + len(entries)

    # Check if evaluation is in terminal state
    stub_path = DATA_DIR / "results" / f"scorecard_{session_id}.json"
    done = False
    if stub_path.exists():
        try:
            stub = json.loads(stub_path.read_text())
            done = stub.get("status") in ("completed", "error", "halted")
        except Exception:
            pass

    return {"entries": entries, "next_offset": next_offset, "done": done}


@router.get("/logs/{session_id}")
async def get_evaluation_log(session_id: str, offset: int = 0):
    """Stream evaluation log entries for the live log panel."""
    return JSONResponse(read_log_entries(session_id=session_id, offset=offset))
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py::test_log_endpoint_offset tests/test_stabilisation.py::test_log_endpoint_done_when_terminal -v
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/api/routes.py tests/test_stabilisation.py
git commit -m "feat: add GET /api/v1/logs/{session_id} streaming endpoint with offset cursor"
```

---

### Task 18: Frontend Live Log Panel

**Files:**
- Modify: `src/governiq/templates/base.html`

- [ ] **Step 1: Add panel HTML to `base.html`**

Add before `</body>` (inside admin-only section if using a portal variable):

```html
{% if portal == 'admin' %}
<div id="eval-log-panel" class="log-panel log-panel--hidden" role="complementary" aria-label="Evaluation Log">
  <div class="log-panel__header">
    <span id="log-panel-title" class="log-panel__title">Evaluation Log</span>
    <div class="log-panel__controls">
      <button onclick="toggleLogPanel()" class="log-btn" id="log-toggle-btn" title="Minimise">—</button>
      <button onclick="closeLogPanel()" class="log-btn" title="Close">✕</button>
    </div>
  </div>
  <div id="log-panel-body" class="log-panel__body">
    <div id="log-entries" class="log-entries"></div>
  </div>
</div>
{% endif %}
```

- [ ] **Step 2: Add CSS**

```css
.log-panel {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  width: 480px;
  max-height: 60vh;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 0.5rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  z-index: 9999;
  font-family: monospace;
  font-size: 0.78rem;
  display: flex;
  flex-direction: column;
}
.log-panel--hidden { display: none; }
.log-panel--minimised .log-panel__body { display: none; }
.log-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: #1e293b;
  border-radius: 0.5rem 0.5rem 0 0;
  cursor: pointer;
}
.log-panel__body { overflow-y: auto; padding: 0.5rem; flex: 1; }
.log-entries { display: flex; flex-direction: column; gap: 2px; }
.log-entry { display: flex; gap: 0.5rem; padding: 2px 0; border-bottom: 1px solid #1e293b; }
.log-entry .ts { color: #64748b; flex-shrink: 0; }
.log-entry .event { flex-shrink: 0; }
.log-entry .detail { color: #cbd5e1; word-break: break-word; }
.log-entry--bot_message .event { color: #60a5fa; }
.log-entry--user_message .event { color: #4ade80; }
.log-entry--check_pass .event, .log-entry--task_complete .event { color: #4ade80; }
.log-entry--check_fail .event, .log-entry--evaluation_halted .event { color: #f87171; }
.log-entry--warn .event, .log-entry--state_seeded .event { color: #fbbf24; }
.log-task-header { color: #94a3b8; font-weight: bold; margin-top: 0.5rem; }
.log-btn { background: none; border: none; color: #94a3b8; cursor: pointer; padding: 0 4px; }
```

- [ ] **Step 3: Add JavaScript polling**

```javascript
(function() {
  let _logSessionId = null;
  let _logOffset = 0;
  let _logPollTimer = null;
  let _lastTaskId = null;
  let _userScrolled = false;

  window.startLogPanel = function(sessionId) {
    _logSessionId = sessionId;
    _logOffset = 0;
    _lastTaskId = null;
    document.getElementById('eval-log-panel').classList.remove('log-panel--hidden');
    document.getElementById('log-panel-title').textContent = 'Evaluation Log — ' + sessionId.substring(0, 8) + '…';
    document.getElementById('log-entries').innerHTML = '';
    sessionStorage.setItem('logSessionId', sessionId);
    _pollLog();
  };

  window.toggleLogPanel = function() {
    document.getElementById('eval-log-panel').classList.toggle('log-panel--minimised');
    localStorage.setItem('logPanelMinimised', document.getElementById('eval-log-panel').classList.contains('log-panel--minimised'));
  };

  window.closeLogPanel = function() {
    document.getElementById('eval-log-panel').classList.add('log-panel--hidden');
    if (_logPollTimer) clearTimeout(_logPollTimer);
    sessionStorage.removeItem('logSessionId');
  };

  function _pollLog() {
    if (!_logSessionId) return;
    fetch('/api/v1/logs/' + _logSessionId + '?offset=' + _logOffset)
      .then(r => r.json())
      .then(data => {
        _appendEntries(data.entries);
        _logOffset = data.next_offset;
        if (!data.done) {
          _logPollTimer = setTimeout(_pollLog, 3000);
        }
      })
      .catch(() => {
        _logPollTimer = setTimeout(_pollLog, 5000);
      });
  }

  function _appendEntries(entries) {
    const container = document.getElementById('log-entries');
    const wasAtBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 10;
    entries.forEach(entry => {
      if (entry.task_id !== _lastTaskId) {
        const header = document.createElement('div');
        header.className = 'log-task-header';
        header.textContent = '▶ ' + entry.task_id;
        container.appendChild(header);
        _lastTaskId = entry.task_id;
      }
      const row = document.createElement('div');
      row.className = 'log-entry log-entry--' + entry.event;
      row.innerHTML =
        '<span class="ts">' + entry.ts.substring(11, 19) + '</span>' +
        '<span class="event">[' + entry.event + ']</span>' +
        '<span class="detail">' + _esc(entry.detail) + '</span>';
      container.appendChild(row);
    });
    if (wasAtBottom && !_userScrolled) {
      container.scrollTop = container.scrollHeight;
    }
  }

  function _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // Restore panel from sessionStorage on page load
  document.addEventListener('DOMContentLoaded', function() {
    const saved = sessionStorage.getItem('logSessionId');
    if (saved) window.startLogPanel(saved);
    if (localStorage.getItem('logPanelMinimised') === 'true') {
      document.getElementById('eval-log-panel')?.classList.add('log-panel--minimised');
    }
  });
})();
```

- [ ] **Step 4: Wire `startLogPanel` to re-run buttons**

In the admin submission list template, update re-run forms to call `startLogPanel` on submit:

```html
<form method="POST" action="/admin/evaluation/{{ s.session_id }}/restart"
      onsubmit="setTimeout(()=>startLogPanel(document.getElementById('new-sid-{{ s.session_id }}')?.value||'{{ s.session_id }}'), 1000)">
```

Or: after the restart redirect, the admin page loads with `?restarted={new_session_id}` in the URL. Add JavaScript on the admin page to detect this and call `startLogPanel`:

```javascript
const params = new URLSearchParams(location.search);
if (params.get('restarted')) {
  startLogPanel(params.get('restarted'));
  history.replaceState({}, '', location.pathname);
}
```

- [ ] **Step 5: Test manually**

Start a real evaluation. Confirm the log panel appears, entries stream in grouped by task, and the panel can be minimised/closed.

- [ ] **Step 6: Commit**

```bash
git add src/governiq/templates/base.html
git commit -m "feat: add floating live log panel with 3s polling, task grouping, colour coding"
```

---

### Task 19: Evidence Integration

**Files:**
- Modify: `src/governiq/core/engine.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_evidence_cards_populated_from_log -v
```

- [ ] **Step 3: Implement `_embed_log_as_evidence` in `engine.py`**

```python
def _embed_log_as_evidence(
    session_id: str,
    task_scores: list,
    logs_dir: Path | None = None,
) -> None:
    """Read JSONL log and append conversation transcript to each TaskScore's evidence_cards."""
    from .scoring import EvidenceCard, EvidenceCardColor
    import json

    logs_dir = logs_dir or Path("./data/logs")
    log_file = logs_dir / f"eval_{session_id}.jsonl"
    if not log_file.exists():
        return

    # Group entries by task_id
    by_task: dict[str, list[dict]] = {}
    try:
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            tid = entry.get("task_id", "unknown")
            by_task.setdefault(tid, []).append(entry)
    except Exception:
        return

    ts_map = {ts.task_id: ts for ts in task_scores}
    for task_id, entries in by_task.items():
        ts = ts_map.get(task_id)
        if not ts:
            continue
        # Build a conversation summary string
        lines = []
        for e in entries:
            if e.get("event") in ("bot_message", "user_message"):
                prefix = "BOT" if e["event"] == "bot_message" else "USER"
                lines.append(f"[{e['ts'][11:19]}] {prefix}: {e.get('detail', '')}")
        if lines:
            card = EvidenceCard(
                card_id=f"log_{task_id}",
                task_id=task_id,
                title="Conversation Transcript",
                content="\n".join(lines),
                color=EvidenceCardColor.BLUE,
                pipeline="webhook",
            )
            ts.evidence_cards.append(card)
```

Call `_embed_log_as_evidence` in `run_full_evaluation` just before writing the final scorecard:

```python
_embed_log_as_evidence(
    session_id=scorecard.session_id,
    task_scores=scorecard.task_scores,
)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py::test_evidence_cards_populated_from_log -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/core/engine.py tests/test_stabilisation.py
git commit -m "feat: embed JSONL conversation log into task evidence_cards on evaluation completion"
```

---

## Phase 5 — Scoring + Health

### Task 20: Health Endpoint Caching + 401 Fix

**Files:**
- Modify: `src/governiq/api/routes.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_health_cache_hit():
    """LLM provider must only be probed once within the TTL window."""
    from unittest.mock import patch, MagicMock
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

    api_routes._health_cache.clear()

    import httpx
    from unittest.mock import patch, MagicMock

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_response
    )

    with patch('httpx.get', return_value=mock_response):
        result = api_routes._check_ai_model()

    assert result["status"] == "failing"
    assert "401" in result["message"] or "invalid" in result["message"].lower()
```

- [ ] **Step 2: Run to confirm failures**

```
pytest tests/test_stabilisation.py::test_health_cache_hit tests/test_stabilisation.py::test_health_401_is_failing -v
```

- [ ] **Step 3: Refactor `_check_ai_model` to add caching and fix 401**

In `api/routes.py`, add the cache dict near the top of the file (module level):

```python
from datetime import datetime, timezone, timedelta

_health_cache: dict[str, dict] = {}
_HEALTH_LLM_TTL = timedelta(seconds=25)
_HEALTH_STORAGE_TTL = timedelta(seconds=300)
```

Extract the actual probe into a separate function:

```python
def _probe_llm_provider(config=None) -> dict:
    """Make a live HTTP call to the configured LLM provider. No caching."""
    if config is None:
        config = load_llm_config()
    probe_url = config.base_url
    if not probe_url:
        return {
            "status": "failing",
            "message": "No AI provider configured. Go to Settings to connect an AI model.",
            "detail": "base_url is empty",
        }

    # Probe strategy differs by provider:
    # - OpenAI-compatible: GET /models (fast, no cost)
    # - Anthropic native: POST /messages with a minimal stub (GET /models not reliable)
    if config.api_format == "anthropic":
        # Use a minimal POST /messages to verify auth — model 'claude-haiku-4-5-20251001', 1 token
        target_url = probe_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": config.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            r = httpx.post(
                target_url,
                headers=headers,
                json={
                    "model": config.model or "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=8.0,
            )
            if r.status_code == 401:
                return {
                    "status": "failing",
                    "message": "API key invalid or unauthorized. Check your Anthropic key in Settings.",
                    "detail": "HTTP 401",
                }
            # 200 or 4xx (e.g. 400 for invalid model) both mean auth succeeded
            return {
                "status": "ok",
                "message": "AI model is connected and ready.",
                "detail": f"HTTP {r.status_code}",
            }
        except httpx.ConnectError:
            return {
                "status": "failing",
                "message": "AI model is not running. Check your Anthropic base URL in Settings.",
                "detail": "Connection refused",
            }
        except Exception as exc:
            return {
                "status": "failing",
                "message": "Could not reach the AI model.",
                "detail": str(exc)[:120],
            }
    else:
        target_url = probe_url.rstrip("/") + "/models"
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        r = httpx.get(target_url, headers=headers, timeout=4.0)
        if r.status_code == 401:
            return {
                "status": "failing",
                "message": "API key invalid or unauthorized. Check your key in Settings.",
                "detail": f"HTTP 401",
            }
        if r.status_code < 500:
            return {
                "status": "ok",
                "message": "AI model is connected and ready.",
                "detail": f"HTTP {r.status_code}",
            }
        return {
            "status": "failing",
            "message": "AI model returned an error. Check that the model is loaded.",
            "detail": f"HTTP {r.status_code}",
        }
    except httpx.ConnectError:
        return {
            "status": "failing",
            "message": "AI model is not running. Start your AI provider and load a model.",
            "detail": "Connection refused",
        }
    except Exception as exc:
        return {
            "status": "failing",
            "message": "Could not reach the AI model.",
            "detail": str(exc)[:120],
        }
```

Update `_check_ai_model` to use the cache:

```python
def _check_ai_model(url: str = "", api_key: str = "") -> dict:
    """Check AI provider with TTL caching to avoid burning rate-limit quota."""
    config = load_llm_config()
    cache_key = f"{config.api_format}:{config.base_url}:{config.model}"

    cached = _health_cache.get(cache_key)
    if cached:
        age = datetime.now(timezone.utc) - cached["cached_at"]
        if age < _HEALTH_LLM_TTL:
            return cached["result"]

    result = _probe_llm_provider(config)
    _health_cache[cache_key] = {"result": result, "cached_at": datetime.now(timezone.utc)}
    return result
```

Update `_check_storage` similarly with a separate cache key and 5-minute TTL.

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py::test_health_cache_hit tests/test_stabilisation.py::test_health_401_is_failing -v
```
Expected: both PASS.

- [ ] **Step 5: Run full suite**

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/api/routes.py tests/test_stabilisation.py
git commit -m "fix: cache health endpoint LLM probe (25s TTL), treat 401 as failing"
```

---

### Task 21: Scorecard `__post_init__` with `scoring_config`

**Files:**
- Modify: `src/governiq/core/scoring.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    # Add a task with webhook_score = 1.0
    ts = TaskScore(task_id="t1", task_name="Task 1")
    ts.webhook_checks = [CheckResult(
        check_id="c1", task_id="t1", pipeline="webhook",
        label="test", status=CheckStatus.PASS, score=1.0
    )]
    sc.task_scores = [ts]
    sc.faq_score = 0.0  # FAQ pipeline RAN but scored 0 — NOT None, so NO redistribution
    # compliance = 1.0 (no compliance results)

    # Expected: 1.0 * 0.60 + 1.0 * 0.20 + 0.0 * 0.20 = 0.80 (no weight redistribution)
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
    """Scorecard without scoring_config must still use 80/10/10 defaults."""
    from src.governiq.core.scoring import Scorecard, TaskScore, CheckResult, CheckStatus

    sc = Scorecard(session_id="s3", candidate_id="c3", manifest_id="m3", assessment_name="T")
    ts = TaskScore(task_id="t1", task_name="Task 1")
    ts.webhook_checks = [CheckResult(
        check_id="c1", task_id="t1", pipeline="webhook",
        label="test", status=CheckStatus.PASS, score=1.0
    )]
    sc.task_scores = [ts]
    # Expected with legacy 80/10/10: 1.0 * 0.80 + 1.0 * 0.10 + 0.0 * 0.10 = 0.90
    assert abs(sc.overall_score - 0.90) < 0.001
```

- [ ] **Step 2: Run to confirm failures**

```
pytest tests/test_stabilisation.py -v -k "scoring"
```

- [ ] **Step 3: Update `Scorecard` in `scoring.py`**

`Scorecard` is a `@dataclass`. Add `scoring_config: dict | None = None` as a field with `field(default=None, repr=False)`, and add `__post_init__`:

```python
from dataclasses import dataclass, field
# At the bottom of the existing field declarations in Scorecard, add:

    scoring_config: dict | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Derive weight attributes from scoring_config or apply legacy defaults."""
        _LEGACY_WEBHOOK = 0.80
        _LEGACY_COMPLIANCE = 0.10
        _LEGACY_FAQ = 0.10
        _LEGACY_THRESHOLD = 0.70

        if self.scoring_config:
            ww = float(self.scoring_config.get("webhook_functional_weight", _LEGACY_WEBHOOK))
            cw = float(self.scoring_config.get("compliance_weight", _LEGACY_COMPLIANCE))
            fw = float(self.scoring_config.get("faq_weight", _LEGACY_FAQ))
            pt = float(self.scoring_config.get("pass_threshold", _LEGACY_THRESHOLD))

            # Validate pass_threshold
            if not (0.5 <= pt <= 1.0):
                import logging
                logging.getLogger(__name__).warning(
                    "Scorecard: pass_threshold %.2f out of range [0.5, 1.0], using 0.70", pt
                )
                pt = _LEGACY_THRESHOLD

            # Normalise weights
            total = ww + cw + fw
            if total > 0 and abs(total - 1.0) > 0.01:
                ww, cw, fw = ww / total, cw / total, fw / total
        else:
            ww, cw, fw, pt = _LEGACY_WEBHOOK, _LEGACY_COMPLIANCE, _LEGACY_FAQ, _LEGACY_THRESHOLD

        self._webhook_weight: float = ww
        self._compliance_weight: float = cw
        self._faq_weight: float = fw
        self._pass_threshold: float = pt
```

Update `overall_score` to use instance weight attributes:

```python
    @property
    def overall_score(self) -> float:
        if not self.task_scores:
            return 0.0
        main_tasks = [t for t in self.task_scores if t.task_id != "faq"]

        # Weight redistribution: if FAQ pipeline did not run (engine sets faq_score=None),
        # redistribute faq_weight to webhook.
        # Note: faq_score=0.0 (FAQ ran but scored zero) does NOT trigger redistribution.
        # The engine must explicitly set faq_score=None when the FAQ pipeline is skipped.
        faq_w = self._faq_weight
        webhook_w = self._webhook_weight
        if self.faq_score is None and faq_w > 0:
            webhook_w = webhook_w + faq_w
            faq_w = 0.0

        if main_tasks:
            task_avg = sum(t.combined_score for t in main_tasks) / len(main_tasks)
        else:
            task_avg = 0.0
        compliance_score = self._compliance_score()
        faq_contribution = (self.faq_score or 0.0) * faq_w
        return task_avg * webhook_w + compliance_score * self._compliance_weight + faq_contribution
```

**Important:** `scoring_config` must NOT appear in `to_dict()` output (it's consumed, not stored). Confirm `to_dict` does not serialise it — the existing `to_dict` only serialises explicitly listed fields, so no change needed.

- [ ] **Step 4: Run tests**

```
pytest tests/test_stabilisation.py -v -k "scoring"
```
Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/core/scoring.py tests/test_stabilisation.py
git commit -m "feat: Scorecard respects manifest scoring_config weights via __post_init__ (CLAUDE.md rule 6)"
```

---

### Task 22: Engine Passes `scoring_config` to Scorecard

**Files:**
- Modify: `src/governiq/core/engine.py`
- Modify: `tests/test_stabilisation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_stabilisation.py`:

```python
def test_engine_passes_scoring_config_to_scorecard():
    """Engine must pass manifest.scoring_config to Scorecard so custom weights are applied end-to-end."""
    import asyncio
    import json
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.governiq.core.engine import EvaluationEngine
    from src.governiq.core.manifest import Manifest

    custom_config = {
        "webhook_functional_weight": 0.60,
        "compliance_weight": 0.20,
        "faq_weight": 0.20,
        "pass_threshold": 0.75,
    }
    manifest = Manifest(
        manifest_id="weight-test-v1",
        assessment_name="Weight Test",
        tasks=[],
        scoring_config=custom_config,
    )

    engine = EvaluationEngine(manifest=manifest, llm_api_key="fake")

    bot_export = {"name": "TestBot"}

    # run_cbm_only with no CBM tasks — returns a Scorecard with defaults
    scorecard = asyncio.run(engine.run_cbm_only(
        bot_export=bot_export,
        candidate_id="test@example.com",
    ))

    # The Scorecard must have the custom weights, not hardcoded 80/10/10
    assert abs(scorecard._webhook_weight - 0.60) < 0.001, (
        f"Expected _webhook_weight=0.60 but got {scorecard._webhook_weight}. "
        "Engine is not passing scoring_config to Scorecard."
    )
    assert abs(scorecard._compliance_weight - 0.20) < 0.001
    assert abs(scorecard._pass_threshold - 0.75) < 0.001
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_stabilisation.py::test_engine_passes_scoring_config_to_scorecard -v
```
Expected: FAIL — `scorecard._webhook_weight` is `0.80` (hardcoded legacy) instead of `0.60`.

- [ ] **Step 3: Find where `Scorecard` is constructed in `engine.py`**

```bash
grep -n "Scorecard(" src/governiq/core/engine.py
```

- [ ] **Step 4: Pass `manifest.scoring_config` to each `Scorecard` constructor call**

For each `Scorecard(...)` call found, add `scoring_config=self.manifest.scoring_config`:

```python
scorecard = Scorecard(
    session_id=...,
    candidate_id=...,
    manifest_id=self.manifest.manifest_id,
    assessment_name=self.manifest.assessment_name,
    scoring_config=self.manifest.scoring_config,   # ADD THIS
)
```

Also log the weights being used at evaluation start:

```python
logger.info(
    "Scoring weights: webhook=%.0f%% compliance=%.0f%% faq=%.0f%% pass_threshold=%.0f%%",
    scorecard._webhook_weight * 100,
    scorecard._compliance_weight * 100,
    scorecard._faq_weight * 100,
    scorecard._pass_threshold * 100,
)
```

- [ ] **Step 5: Run the new wire-up test**

```
pytest tests/test_stabilisation.py::test_engine_passes_scoring_config_to_scorecard -v
```
Expected: PASS.

- [ ] **Step 6: Run full test suite**

```
pytest tests/ -q
```
Expected: same pass/skip counts as before — no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/governiq/core/engine.py tests/test_stabilisation.py
git commit -m "feat: engine passes manifest scoring_config to Scorecard constructor"
```

---

## Final Verification

- [ ] **Run the complete test suite one last time**

```
pytest tests/ -v --tb=short
```
Expected: all previously passing tests still pass + all new tests pass.

- [ ] **Start the server and do a full smoke test**

```
uvicorn src.governiq.main:app --reload --port 8000
```

Verify manually:
1. Navigate to `/candidate/` — dropdowns are readable (not white-on-white)
2. Navigate to `/admin/settings` — API key field has show/hide toggle, saving shows verification result
3. Submit an evaluation — stub written with all new fields
4. Navigate to `/admin/` — all submission statuses visible with correct badges
5. Navigate to `/candidate/history` — no 500 error even if error stubs are on disk
6. Wait for an evaluation to run — log panel appears, streams in real time

- [ ] **Final commit** (only if any uncommitted changes remain after the phase commits)

```bash
git status  # review what's uncommitted — do NOT blindly add everything
# Stage only source and test files — never .env, data/, or *.jsonl files
git add \
  src/governiq/core/exceptions.py \
  src/governiq/core/eval_logger.py \
  src/governiq/webhook/message_normaliser.py \
  src/governiq/candidate/routes.py \
  src/governiq/core/engine.py \
  src/governiq/webhook/driver.py \
  src/governiq/core/scoring.py \
  src/governiq/api/routes.py \
  src/governiq/admin/routes.py \
  src/governiq/templates/ \
  tests/test_eval_logger.py \
  tests/test_message_normaliser.py \
  tests/test_stabilisation.py \
  docs/superpowers/plans/2026-03-20-stabilisation-sprint.md
git commit -m "chore: stabilisation sprint complete — all tests passing"
```
