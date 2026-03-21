# Bot Pre-Registration + Credential Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bot pre-registration with credential persistence, fix restart/review bugs, add live eval conversation log, and apply a full CSS design system overhaul with admin-configurable platform URL.

**Architecture:** Four sprint areas in dependency order: (1) shared infrastructure (`platform_config.py`, `registration.py`, `jwt_auth.py` hardening); (2) restart + review bug fixes; (3) eval observability via JSONL structured events + SSE streaming; (4) CSS design system applied to all 16 templates. All routes are FastAPI + Jinja2. No new packages.

**Tech Stack:** Python 3.14, FastAPI, Jinja2, httpx, dataclasses (no Pydantic for new models — follows `KoreCredentials` pattern), SSE via `StreamingResponse` + async generator, Lucide icons (already loaded in `base.html`).

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/governiq/core/platform_config.py` | `load_platform_config`, `save_platform_config`, `get_kore_platform_url` |
| `src/governiq/candidate/registration.py` | `BotRegistration` dataclass, `load_bot_registration`, `save_bot_registration`, `list_bot_registrations`, `to_kore_credentials` |
| `src/governiq/templates/candidate_register.html` | Bot registration form (Option C sectioned layout) |
| `src/governiq/templates/admin_bots.html` | Admin bot registry table |
| `src/governiq/templates/admin_conversation.html` | Per-eval live conversation log page (SSE + historical) |
| `tests/test_platform_config.py` | Tests for `platform_config.py` + admin settings platform route |
| `tests/test_bot_registration.py` | Tests for registration, restart fixes, review endpoint |

### Modified files
| File | What changes |
|------|-------------|
| `src/governiq/webhook/jwt_auth.py` | `platform_url` default → `""`; `validate()` adds `bot_name` non-empty check |
| `src/governiq/candidate/routes.py` | Add register routes; refactor submit to load creds from registration; add `bot_id` to stub; `GET /` gains `?bot_id` param |
| `src/governiq/admin/routes.py` | Fix restart (manifest-first ordering, no orphan stubs); fix review (safe-defaulted context); add `/admin/bots`, `POST /admin/settings/platform`, `/admin/evaluation/{id}/stream|conversation|log`; restart gains credential pre-fill from registration + jwtgrant pre-flight |
| `src/governiq/api/routes.py` | Replace `os.environ.get("KORE_PLATFORM_URL", ...)` with `get_kore_platform_url()` |
| `src/governiq/webhook/driver.py` | Session `{"new": False}` on all turns after first; pass `task_id` + `step` to EvalLogger calls |
| `src/governiq/webhook/kore_api.py` | Add `get_sessions_by_user(from_id)` async method |
| `src/governiq/core/engine.py` | Wire all EvalLogger structured event calls; call `get_sessions_by_user` post-eval; store `session_id` at init |
| `src/governiq/core/eval_logger.py` | Add 11 structured event methods (`_emit` helper + one method per event type) |
| `src/governiq/templates/base.html` | Full CSS design system (spec sections 2.1–2.10); updated `toggleVisibility()` |
| `src/governiq/templates/admin_dashboard.html` | New badge/button/halt-reason pattern; Watch Live + View Log buttons |
| `src/governiq/templates/admin_settings.html` | Kore.ai Platform Defaults section card + `kore_platform_url` context var |
| `src/governiq/templates/admin_review.html` | Safe-defaulted context vars; section-icon headers |
| `src/governiq/templates/admin_compare.html` | `.tbl`, `.section-icon`, new badge classes |
| `src/governiq/templates/admin_manifest_list.html` | `.tbl` with `vertical-align:middle` |
| `src/governiq/templates/admin_manifest_editor.html` | `.form-section-hdr` + input-group for secret fields |
| `src/governiq/templates/admin_manifest_schema.html` | CSS only — inherits updated base vars; no markup changes |
| `src/governiq/templates/candidate_submit.html` | Replace credential block with Bot Card + bot_id hidden field + lookup form |
| `src/governiq/templates/candidate_history.html` | `.tbl` + badge/score-pill pattern |
| `src/governiq/templates/candidate_report.html` | Score reveal with pass/fail banner and pipeline breakdown |
| `src/governiq/templates/landing.html` | Dark theme hero + feature cards using `--card-bg`/`--card-border` vars |
| `src/governiq/templates/error.html` | CSS only — inherits updated base vars |
| `src/governiq/templates/how_it_works.html` | CSS only — inherits updated base vars |

---

## Task 1: Platform Config Module

**Files:**
- Create: `src/governiq/core/platform_config.py`
- Create: `tests/test_platform_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_platform_config.py
"""Tests for platform_config — admin-configurable Kore.ai platform URL."""
import json
import pytest


def test_get_kore_platform_url_returns_default_when_no_file(tmp_path, monkeypatch):
    from src.governiq.core import platform_config as pc
    monkeypatch.setattr(pc, "PLATFORM_CONFIG_PATH", tmp_path / "platform_config.json")
    assert pc.get_kore_platform_url() == "https://platform.kore.ai/"


def test_get_kore_platform_url_returns_saved_value(tmp_path, monkeypatch):
    from src.governiq.core import platform_config as pc
    p = tmp_path / "platform_config.json"
    p.write_text(json.dumps({"kore_platform_url": "https://custom.kore.ai/"}))
    monkeypatch.setattr(pc, "PLATFORM_CONFIG_PATH", p)
    assert pc.get_kore_platform_url() == "https://custom.kore.ai/"


def test_load_platform_config_returns_default_on_corrupt_json(tmp_path, monkeypatch):
    from src.governiq.core import platform_config as pc
    p = tmp_path / "platform_config.json"
    p.write_text("not json {{")
    monkeypatch.setattr(pc, "PLATFORM_CONFIG_PATH", p)
    result = pc.load_platform_config()
    assert result["kore_platform_url"] == "https://platform.kore.ai/"


def test_save_platform_config_writes_json(tmp_path, monkeypatch):
    from src.governiq.core import platform_config as pc
    p = tmp_path / "platform_config.json"
    monkeypatch.setattr(pc, "PLATFORM_CONFIG_PATH", p)
    pc.save_platform_config("https://my.kore.ai/")
    data = json.loads(p.read_text())
    assert data["kore_platform_url"] == "https://my.kore.ai/"
    assert "updated_at" in data
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_platform_config.py -v
```
Expected: `ModuleNotFoundError` — module does not exist yet.

- [ ] **Step 3: Create `platform_config.py`**

```python
# src/governiq/core/platform_config.py
"""Admin-configurable Kore.ai platform URL — stored in data/platform_config.json."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

# Absolute path — safe regardless of Uvicorn working directory
PLATFORM_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "data" / "platform_config.json"
DEFAULT_KORE_PLATFORM_URL = "https://platform.kore.ai/"


def load_platform_config() -> dict:
    if PLATFORM_CONFIG_PATH.exists():
        try:
            return json.loads(PLATFORM_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {"kore_platform_url": DEFAULT_KORE_PLATFORM_URL}


def save_platform_config(kore_platform_url: str) -> None:
    PLATFORM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLATFORM_CONFIG_PATH.write_text(json.dumps({
        "kore_platform_url": kore_platform_url.strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def get_kore_platform_url() -> str:
    return load_platform_config().get("kore_platform_url", DEFAULT_KORE_PLATFORM_URL)
```

- [ ] **Step 4: Run tests — expect all pass**

```
pytest tests/test_platform_config.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/core/platform_config.py tests/test_platform_config.py
git commit -m "feat: add platform_config module — admin-configurable Kore.ai URL"
```

---

## Task 2: Bot Registration Module

**Files:**
- Create: `src/governiq/candidate/registration.py`
- Create: `tests/test_bot_registration.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bot_registration.py
"""Tests for bot registration, restart bug fixes, and review endpoint."""
import json
import uuid
import pytest


def _reg_dict(**kwargs):
    defaults = {
        "bot_id": "st-abc123",
        "bot_name": "TestBot",
        "client_id": "cs-abc123",
        "client_secret": "secret",
        "webhook_url": "https://platform.kore.ai/hooks/abc",
        "platform_url": "https://platform.kore.ai/",
        "registered_by": "user@test.com",
        "registered_at": "2026-03-21T10:00:00+00:00",
        "credential_verified_at": "2026-03-21T10:00:00+00:00",
        "credential_status": "verified",
    }
    return {**defaults, **kwargs}


def test_load_bot_registration_returns_registration(tmp_path):
    from src.governiq.candidate.registration import BotRegistration, load_bot_registration, save_bot_registration
    reg = BotRegistration(**_reg_dict())
    save_bot_registration(reg, reg_dir=tmp_path)
    loaded = load_bot_registration("st-abc123", reg_dir=tmp_path)
    assert loaded is not None
    assert loaded.bot_name == "TestBot"


def test_load_bot_registration_returns_none_for_missing(tmp_path):
    from src.governiq.candidate.registration import load_bot_registration
    assert load_bot_registration("st-notexist", reg_dir=tmp_path) is None


def test_to_kore_credentials_maps_fields(tmp_path):
    from src.governiq.candidate.registration import BotRegistration, to_kore_credentials
    reg = BotRegistration(**_reg_dict())
    creds = to_kore_credentials(reg)
    assert creds.bot_id == "st-abc123"
    assert creds.bot_name == "TestBot"
    assert creds.platform_url == "https://platform.kore.ai/"


def test_to_kore_credentials_raises_on_empty_bot_name():
    from src.governiq.candidate.registration import BotRegistration, to_kore_credentials
    reg = BotRegistration(**_reg_dict(bot_name=""))
    with pytest.raises(ValueError, match="bot_name"):
        to_kore_credentials(reg)


def test_save_bot_registration_writes_json(tmp_path):
    from src.governiq.candidate.registration import BotRegistration, save_bot_registration
    reg = BotRegistration(**_reg_dict())
    save_bot_registration(reg, reg_dir=tmp_path)
    saved = json.loads((tmp_path / "st-abc123.json").read_text())
    assert saved["bot_name"] == "TestBot"
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/test_bot_registration.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `registration.py`**

```python
# src/governiq/candidate/registration.py
"""Bot registration storage — persists Kore.ai credentials per bot_id."""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path

_DEFAULT_REG_DIR = Path(__file__).parent.parent.parent.parent / "data" / "bot_registrations"


@dataclass
class BotRegistration:
    bot_id: str
    bot_name: str
    client_id: str
    client_secret: str
    webhook_url: str
    platform_url: str
    registered_by: str
    registered_at: str
    credential_verified_at: str = ""
    credential_status: str = "unverified"  # "verified" | "failed" | "unverified"


def load_bot_registration(bot_id: str, reg_dir: Path | None = None) -> BotRegistration | None:
    reg_dir = reg_dir or _DEFAULT_REG_DIR
    path = reg_dir / f"{bot_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        fields = BotRegistration.__dataclass_fields__
        return BotRegistration(**{k: data[k] for k in fields if k in data})
    except Exception:
        return None


def save_bot_registration(reg: BotRegistration, reg_dir: Path | None = None) -> None:
    reg_dir = reg_dir or _DEFAULT_REG_DIR
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / f"{reg.bot_id}.json").write_text(json.dumps(asdict(reg), indent=2))


def list_bot_registrations(reg_dir: Path | None = None) -> list[BotRegistration]:
    reg_dir = reg_dir or _DEFAULT_REG_DIR
    if not reg_dir.exists():
        return []
    results = []
    for p in sorted(reg_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            fields = BotRegistration.__dataclass_fields__
            results.append(BotRegistration(**{k: data[k] for k in fields if k in data}))
        except Exception:
            continue
    return results


def to_kore_credentials(reg: BotRegistration):
    """Convert a BotRegistration to KoreCredentials. Raises ValueError on invalid data."""
    from ..webhook.jwt_auth import KoreCredentials
    creds = KoreCredentials(
        bot_id=reg.bot_id,
        client_id=reg.client_id,
        client_secret=reg.client_secret,
        bot_name=reg.bot_name,
        platform_url=reg.platform_url,
    )
    errors = creds.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return creds
```

- [ ] **Step 4: Run tests — expect all pass**

```
pytest tests/test_bot_registration.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/candidate/registration.py tests/test_bot_registration.py
git commit -m "feat: add BotRegistration module — load/save/list/to_kore_credentials"
```

---

## Task 3: jwt_auth.py — bot_name Validation + platform_url Default

**Files:**
- Modify: `src/governiq/webhook/jwt_auth.py`

- [ ] **Step 1: Add tests**

Append to `tests/test_bot_registration.py`:

```python
def test_kore_credentials_validate_requires_bot_name():
    from src.governiq.webhook.jwt_auth import KoreCredentials
    creds = KoreCredentials(bot_id="st-x", client_id="cs-x", client_secret="s", bot_name="")
    errors = creds.validate()
    assert any("bot_name" in e.lower() for e in errors)


def test_kore_credentials_platform_url_default_is_empty():
    from src.governiq.webhook.jwt_auth import KoreCredentials
    creds = KoreCredentials(bot_id="st-x", client_id="cs-x", client_secret="s", bot_name="Bot")
    assert creds.platform_url == ""
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/test_bot_registration.py::test_kore_credentials_validate_requires_bot_name tests/test_bot_registration.py::test_kore_credentials_platform_url_default_is_empty -v
```
Expected: both FAIL.

- [ ] **Step 3: Edit `jwt_auth.py`**

At line 37, change:
```python
    platform_url: str = "https://bots.kore.ai"
```
to:
```python
    platform_url: str = ""
```

In `validate()` (lines 39–48), add after the existing three checks:
```python
        if not self.bot_name:
            errors.append("bot_name is required for Kore.ai jwtgrant authentication.")
```

- [ ] **Step 4: Run full test suite**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```
Expected: all PASS (including new tests).

- [ ] **Step 5: Commit**

```bash
git add src/governiq/webhook/jwt_auth.py tests/test_bot_registration.py
git commit -m "fix: jwt_auth — enforce bot_name in validate(); platform_url default empty string"
```

---

## Task 4: Restart Bug Fix — Manifest-First, No Orphan Stubs

**Files:**
- Modify: `src/governiq/admin/routes.py`

- [ ] **Step 1: Add test for orphan stub prevention**

Append to `tests/test_bot_registration.py`:

```python
def _make_stub(tmp_path, **kwargs):
    """Write a minimal stub file, return (stub_dict, stub_path)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    session_id = kwargs.get("session_id", str(uuid.uuid4()))
    stub = {
        "session_id": session_id,
        "status": "completed",
        "candidate_id": "test@test.com",
        "manifest_id": kwargs.get("manifest_id", ""),
        "assessment_name": kwargs.get("assessment_name", ""),
        "webhook_url": "https://example.com/hook",
        "submitted_at": "2026-03-21T10:00:00+00:00",
        "completed_tasks": [],
        "halt_reason": None,
        "halted_on_task": None,
        "halted_at": None,
        "parent_session_id": None,
        "log_file": f"data/logs/eval_{session_id}.jsonl",
        "error": None,
    }
    path = results_dir / f"scorecard_{session_id}.json"
    path.write_text(json.dumps(stub))
    return stub, path


def test_restart_no_orphan_stub_when_manifest_missing(tmp_path, monkeypatch):
    """When manifest_id and assessment_name are both empty, restart must return 4xx
    WITHOUT creating a new stub file."""
    import src.governiq.admin.routes as ar
    monkeypatch.setattr(ar, "DATA_DIR", tmp_path)
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    monkeypatch.setattr(ar, "MANIFESTS_DIR", manifests_dir)

    # Need an uploads dir to pass the zip check — create a fake upload
    stub, _ = _make_stub(tmp_path, manifest_id="", assessment_name="")
    session_id = stub["session_id"]
    upload_dir = tmp_path / "uploads" / session_id
    upload_dir.mkdir(parents=True)
    (upload_dir / "bot_export.json").write_text("{}")

    from fastapi.testclient import TestClient
    from src.governiq.main import app
    client = TestClient(app)
    resp = client.post(f"/admin/evaluation/{session_id}/restart", data={"mode": "fresh"})

    assert resp.status_code in (400, 404, 422)
    stubs = list((tmp_path / "results").glob("scorecard_*.json"))
    assert len(stubs) == 1, f"Expected 1 stub, got {len(stubs)}: {[s.name for s in stubs]}"
```

- [ ] **Step 2: Run to confirm it fails (the bug exists)**

```
pytest tests/test_bot_registration.py::test_restart_no_orphan_stub_when_manifest_missing -v
```
Expected: FAIL — currently a second stub IS written before the manifest lookup fails.

- [ ] **Step 3: Fix `mode == "fresh"` branch**

In `admin/routes.py`, the `mode == "fresh"` block (around line 1028) currently:
1. Checks upload exists
2. Writes new stub to disk  ← BUG: happens before manifest lookup
3. Looks up manifest
4. Returns error if not found (stub is now orphaned)

Reorder to:
1. Check upload exists
2. Look up manifest (by `manifest_id` first, then `assessment_name` fallback — only when assessment_name is non-empty)
3. Return 422 if manifest not found (no stub written yet)
4. Write new stub only after manifest found — inject `manifest_id` and `assessment_name` **explicitly from `manifest_obj`** (not just via `**original_stub` spread)
5. Continue with background task dispatch

The manifest lookup logic:
```python
        manifest_id = original_stub.get("manifest_id", "").strip()
        manifest_obj = None
        if manifest_id:
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
            # Assessment name fallback — only when non-empty
            assessment_name = original_stub.get("assessment_name", "").strip()
            if assessment_name:
                for mf in MANIFESTS_DIR.glob("*.json"):
                    try:
                        mdata = json.loads(mf.read_text())
                        if mdata.get("assessment_name", "").strip() == assessment_name:
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
        # Now write the stub — manifest is confirmed to exist
        new_session_id = str(uuid.uuid4())
        new_stub_path = results_dir / f"scorecard_{new_session_id}.json"
        new_stub = {
            **original_stub,
            "session_id": new_session_id,
            "status": "running",
            "manifest_id": manifest_obj.manifest_id,          # explicit — not just spread
            "assessment_name": manifest_obj.assessment_name,  # explicit
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
```

Apply the same fix to the `mode == "resume"` branch (around line 1133). The `mode == "resume"` branch has the same bug in the same order.

- [ ] **Step 4: Run tests**

```
pytest tests/test_bot_registration.py::test_restart_no_orphan_stub_when_manifest_missing -v
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```
Expected: orphan stub test PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/admin/routes.py tests/test_bot_registration.py
git commit -m "fix: restart handler — manifest lookup before stub creation; no orphan stubs"
```

---

## Task 5: Review Endpoint — Defensive Context Dict

**Files:**
- Modify: `src/governiq/admin/routes.py`
- Modify: `src/governiq/templates/admin_review.html`

- [ ] **Step 1: Add test**

Append to `tests/test_bot_registration.py`:

```python
def test_review_endpoint_renders_with_minimal_stub(tmp_path, monkeypatch):
    """Review endpoint must not 500 when stub has only minimal fields."""
    import src.governiq.admin.routes as ar
    monkeypatch.setattr(ar, "DATA_DIR", tmp_path)
    results_dir = tmp_path / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid.uuid4())
    stub = {"session_id": session_id, "status": "error", "log_file": ""}
    (results_dir / f"scorecard_{session_id}.json").write_text(json.dumps(stub))

    from fastapi.testclient import TestClient
    from src.governiq.main import app
    client = TestClient(app)
    resp = client.get(f"/admin/review/{session_id}")
    assert resp.status_code == 200
    assert session_id in resp.text
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_bot_registration.py::test_review_endpoint_renders_with_minimal_stub -v
```
Expected: FAIL (500 or assertion error).

- [ ] **Step 3: Fix the review GET handler in `admin/routes.py`**

Find `GET /admin/review/{session_id}`. Replace the template context construction with an explicit safe-defaulted dict:

```python
    context = {
        "request": request,
        "portal": "admin",
        "session_id": stub.get("session_id", session_id),
        "candidate_id": stub.get("candidate_id", "N/A"),
        "assessment_name": stub.get("assessment_name", "N/A"),
        "manifest_id": stub.get("manifest_id", ""),
        "overall_score": stub.get("overall_score", None),
        "status": stub.get("status", "unknown"),
        "submitted_at": stub.get("submitted_at", ""),
        "completed_at": stub.get("completed_at", ""),
        "task_scores": stub.get("task_scores", []),
        "compliance_results": stub.get("compliance_results", []),
        "halt_reason": stub.get("halt_reason", None),
        "halted_on_task": stub.get("halted_on_task", None),
        "error": stub.get("error", None),
        "webhook_url": stub.get("webhook_url", ""),
        "bot_id": stub.get("bot_id", ""),
        "log_file": stub.get("log_file", ""),
        "parent_session_id": stub.get("parent_session_id", None),
        "kore_session_id": stub.get("kore_session_id", None),
        "plag_report": stub.get("plag_report", None),
    }
    return templates.TemplateResponse("admin_review.html", context)
```

Then update `admin_review.html`: change any `{{ sc.field }}` references to `{{ field }}`. Add `| default("Not available")` on any field that may be missing. Read the template first to find all attribute access patterns.

- [ ] **Step 4: Run test**

```
pytest tests/test_bot_registration.py::test_review_endpoint_renders_with_minimal_stub -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/admin/routes.py src/governiq/templates/admin_review.html tests/test_bot_registration.py
git commit -m "fix: review endpoint — defensive context dict; renders without 500 on minimal stub"
```

---

## Task 6: EvalLogger Structured Event Methods

**Files:**
- Modify: `src/governiq/core/eval_logger.py`
- Modify: `tests/test_eval_logger.py`

Before editing, read `tests/test_eval_logger.py` to understand the existing test style.

- [ ] **Step 1: Add tests**

Append to `tests/test_eval_logger.py`:

```python
def test_log_webhook_turn_sent_writes_type_key(tmp_path):
    import json
    from src.governiq.core.eval_logger import EvalLogger
    el = EvalLogger("sess-001", log_dir=tmp_path)
    el.log_webhook_turn_sent("T1", 1, "Hello bot")
    lines = (tmp_path / "eval_sess-001.jsonl").read_text().strip().splitlines()
    ev = json.loads(lines[-1])
    assert ev["type"] == "webhook_turn_sent"
    assert ev["content"] == "Hello bot"
    assert ev["task_id"] == "T1"
    assert ev["step"] == 1
    assert "ts" in ev


def test_log_eval_completed_writes_final_score(tmp_path):
    import json
    from src.governiq.core.eval_logger import EvalLogger
    el = EvalLogger("sess-002", log_dir=tmp_path)
    el.log_eval_completed("sess-002", 87.5)
    lines = (tmp_path / "eval_sess-002.jsonl").read_text().strip().splitlines()
    ev = json.loads(lines[-1])
    assert ev["type"] == "eval_completed"
    assert ev["final_score"] == 87.5
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_eval_logger.py -k "webhook_turn_sent or eval_completed" -v
```

- [ ] **Step 3: Add `_emit` helper and 11 methods to `eval_logger.py`**

Append after the existing `log()` method:

```python
    def _emit(self, event: dict) -> None:
        """Write a new-schema structured event directly (uses 'type' key, not 'event')."""
        if self._line_count >= _MAX_LINES:
            return
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        try:
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            self._line_count += 1
        except Exception:
            pass

    def log_eval_started(self, session_id: str) -> None:
        self._emit({"type": "eval_started", "session_id": session_id})

    def log_eval_completed(self, session_id: str, final_score: float) -> None:
        self._emit({"type": "eval_completed", "session_id": session_id, "final_score": final_score})

    def log_task_started(self, task_id: str, task_name: str) -> None:
        self._emit({"type": "task_started", "task_id": task_id, "task_name": task_name})

    def log_task_completed(self, task_id: str, task_name: str, passed: bool) -> None:
        self._emit({"type": "task_completed", "task_id": task_id, "task_name": task_name, "passed": passed})

    def log_task_failed(self, task_id: str, task_name: str, reason: str) -> None:
        self._emit({"type": "task_failed", "task_id": task_id, "task_name": task_name, "reason": reason})

    def log_webhook_turn_sent(self, task_id: str, step: int, content: str) -> None:
        self._emit({"type": "webhook_turn_sent", "task_id": task_id, "step": step, "content": content})

    def log_webhook_turn_received(self, task_id: str, step: int, content: str) -> None:
        self._emit({"type": "webhook_turn_received", "task_id": task_id, "step": step, "content": content})

    def log_intent_classified(self, task_id: str, step: int, intent: str, method: str) -> None:
        self._emit({"type": "intent_classified", "task_id": task_id, "step": step, "intent": intent, "method": method})

    def log_entity_injected(self, task_id: str, step: int, entity_key: str, value: str) -> None:
        self._emit({"type": "entity_injected", "task_id": task_id, "step": step, "entity_key": entity_key, "value": value})

    def log_llm_call(self, task_id: str, purpose: str, result: str) -> None:
        self._emit({"type": "llm_call", "task_id": task_id, "purpose": purpose, "result": result})

    def log_engine_error(self, task_id: str, error: str, halt_reason: str) -> None:
        self._emit({"type": "engine_error", "task_id": task_id, "error": error, "halt_reason": halt_reason})
```

- [ ] **Step 4: Run all logger tests**

```
pytest tests/test_eval_logger.py -v
```
Expected: all PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/governiq/core/eval_logger.py tests/test_eval_logger.py
git commit -m "feat: EvalLogger — 11 structured event methods; _emit helper with 'type' key schema"
```

---

## Task 7: driver.py — Session Fix + EvalLogger Passthrough

**Files:**
- Modify: `src/governiq/webhook/driver.py`

Read `driver.py` first, focusing on `KoreWebhookClient.__init__`, `send_message`, and the session payload building block.

- [ ] **Step 1: Fix the session payload**

Find the block in `KoreWebhookClient.send_message` that sets `payload["session"]`. The current logic sends `session.id = kore_session_id` on subsequent messages. Replace with:

```python
        if self._is_new_session:
            payload["session"] = {"new": True}
            self._is_new_session = False
        else:
            payload["session"] = {"new": False}
```

`_kore_session_id` is still stored when received in the response (for post-eval getSessions lookup) but is no longer sent back in subsequent payloads. Add `self._is_new_session = True` in `__init__` if not already present.

- [ ] **Step 2: Add EvalLogger call sites**

Add two new instance attributes to `KoreWebhookClient.__init__`:
```python
        self._current_task_id: str = ""
        self._current_step: int = 0
```

After the webhook POST succeeds and the user message is sent, log it:
```python
        if self._eval_logger:
            self._eval_logger.log_webhook_turn_sent(
                self._current_task_id, self._current_step, message_text
            )
```

After the normalised bot response text is extracted, log it:
```python
        if self._eval_logger:
            self._eval_logger.log_webhook_turn_received(
                self._current_task_id, self._current_step, bot_text
            )
```

In `LLMConversationDriver`, after an LLM intent classification result is returned, log it. The classify methods need `task_id` and `step` added as parameters (passed through from the engine). Add to `log_intent_classified` call:
```python
        if self._eval_logger:
            self._eval_logger.log_intent_classified(task_id, step, intent, "llm")
```

For entity injection events, add to wherever entity values are selected:
```python
        if self._eval_logger:
            self._eval_logger.log_entity_injected(task_id, step, entity_key, str(value))
```

For LLM calls, add after the LLM response text is extracted:
```python
        if self._eval_logger:
            self._eval_logger.log_llm_call(task_id, "classification", result_text)
```

Note: Read the actual method signatures in `driver.py` before adding calls — match parameter names exactly. If a method does not yet accept `task_id`/`step`, add them as optional params with defaults `""` and `0`.

- [ ] **Step 3: Update docstrings**

In `KoreWebhookClient.send_message` docstring, remove any language about "Subsequent: session.id = pinned koreSessionId". Replace with: "Subsequent messages send `session: {new: False}` — continuity is maintained by `from.id`."

- [ ] **Step 4: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/webhook/driver.py
git commit -m "fix: driver — session:{new:false} on subsequent turns; EvalLogger passthrough"
```

---

## Task 8: kore_api.py — get_sessions_by_user

**Files:**
- Modify: `src/governiq/webhook/kore_api.py`

Read `kore_api.py` first to understand `KoreAPIClient._ensure_token()` and the existing `_api_get` pattern.

- [ ] **Step 1: Add method to `KoreAPIClient`**

```python
    async def get_sessions_by_user(self, from_id: str) -> str | None:
        """Return the most recent sessionId for from_id, or None on any failure."""
        try:
            token = await self._ensure_token()
            endpoint = (
                f"{self.credentials.platform_url.rstrip('/')}"
                f"/api/public/bot/{self.credentials.bot_id}/getSessions"
            )
            params = {"userId": from_id, "channel": "webhook", "limit": 1}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    endpoint,
                    params=params,
                    headers={"Authorization": f"bearer {token}"},
                )
            resp.raise_for_status()
            data = resp.json()
            sessions = data.get("sessions", [])
            if sessions:
                return sessions[0].get("sessionId")
            return None
        except Exception as exc:
            logger.warning("get_sessions_by_user failed for %s: %s", from_id, exc)
            return None
```

Note: uses its own `httpx.AsyncClient` with the full absolute endpoint URL because `_api_get` uses a base URL that may not include the platform path.

- [ ] **Step 2: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/governiq/webhook/kore_api.py
git commit -m "feat: kore_api — get_sessions_by_user for post-eval session ID lookup"
```

---

## Task 9: engine.py — EvalLogger Integration + Post-Eval getSessions

**Files:**
- Modify: `src/governiq/core/engine.py`

Read `engine.py` from line 60 to the end. Pay attention to:
- `EvaluationEngine.__init__` signature (find where `session_id` is stored or should be added)
- `run_full_evaluation` — the task iteration loop, exception handlers, and return value
- Where `KoreWebhookClient` and `KoreAPIClient` are constructed

- [ ] **Step 1: Store `session_id` in `__init__`**

In `EvaluationEngine.__init__`, add:
```python
        self._session_id: str = ""  # set by caller via engine.set_session_id()
```

Or accept `session_id` as a constructor parameter if that is the cleaner change. The value is the `session_id` string from the scorecard stub. Check how `EvaluationEngine` is constructed in `_run_evaluation_background` in `candidate/routes.py` to see what is already passed.

- [ ] **Step 2: Wire EvalLogger calls in `run_full_evaluation`**

At the very top of `run_full_evaluation`, before the task loop:
```python
        if self._eval_logger:
            self._eval_logger.log_eval_started(self._session_id)
```

Before each task runs (in the task iteration loop):
```python
            if self._eval_logger:
                self._eval_logger.log_task_started(task.task_id, task.task_name)
```

Before each `_webhook_client._current_task_id = task.task_id` assignment (or wherever the per-task context is set):
```python
            if self._webhook_client:
                self._webhook_client._current_task_id = task.task_id
                self._webhook_client._current_step = 0
```

After each task result is determined:
```python
            if self._eval_logger:
                if task_passed:
                    self._eval_logger.log_task_completed(task.task_id, task.task_name, True)
                else:
                    self._eval_logger.log_task_failed(task.task_id, task.task_name, reason)
```

In the `EvaluationHaltedError` exception handler:
```python
            if self._eval_logger:
                self._eval_logger.log_engine_error(task.task_id, str(exc), str(exc))
```

At the end, before returning:
```python
        if self._eval_logger:
            self._eval_logger.log_eval_completed(
                self._session_id,
                scorecard.overall_score if scorecard else 0.0,
            )
```

- [ ] **Step 3: Add post-eval getSessions call**

After all tasks complete and the scorecard is ready but before returning it, add:

```python
        # Post-eval: look up the Kore.ai session ID for debug access
        kore_session_id = None
        if self._kore_creds and self._kore_api_client:
            try:
                from_id = self._webhook_client._from_id if self._webhook_client else ""
                if from_id:
                    kore_session_id = await self._kore_api_client.get_sessions_by_user(from_id)
            except Exception as exc:
                logger.warning("Post-eval getSessions failed: %s", exc)
```

Add `kore_session_id` to the scorecard dict. Check `scoring.py` to see how `Scorecard.to_dict()` works — either add `kore_session_id` as an optional field on `Scorecard`, or inject it after calling `to_dict()` in the caller. The simpler approach: inject it in `_run_evaluation_background` after `scorecard.to_dict()`:

```python
        result_dict = scorecard.to_dict()
        result_dict["kore_session_id"] = kore_session_id  # may be None
        with stub_path.open("w") as f:
            json.dump(result_dict, f, indent=2)
```

- [ ] **Step 4: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governiq/core/engine.py src/governiq/candidate/routes.py
git commit -m "feat: engine — EvalLogger structured events; post-eval getSessions lookup"
```

---

## Task 10: Candidate Registration Routes

**Files:**
- Modify: `src/governiq/candidate/routes.py`

Read the top of `candidate/routes.py` to understand existing imports, `DATA_DIR`, and `router` setup.

- [ ] **Step 1: Add imports**

At the top of `candidate/routes.py`, add:
```python
from .registration import BotRegistration, load_bot_registration, save_bot_registration
from ..core.platform_config import get_kore_platform_url
```

- [ ] **Step 2: Add the three registration routes**

```python
@router.get("/register")
async def get_register(request: Request):
    return templates.TemplateResponse("candidate_register.html", {
        "request": request,
        "portal": "candidate",
        "kore_platform_url": get_kore_platform_url(),
        "error": None,
    })


@router.post("/register")
async def post_register(
    request: Request,
    bot_id: str = Form(...),
    bot_name: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
    webhook_url: str = Form(...),
    platform_url: str = Form(...),
    registered_by: str = Form(""),
):
    from datetime import datetime, timezone
    from ..webhook.jwt_auth import KoreCredentials, get_kore_bearer_token

    creds = KoreCredentials(
        bot_id=bot_id.strip(),
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        bot_name=bot_name.strip(),
        platform_url=platform_url.strip() or get_kore_platform_url(),
    )
    validation_errors = creds.validate()
    if validation_errors:
        return templates.TemplateResponse("candidate_register.html", {
            "request": request, "portal": "candidate",
            "kore_platform_url": platform_url,
            "error": "; ".join(validation_errors),
        })

    try:
        await get_kore_bearer_token(creds, max_retries=0)
    except Exception as exc:
        err_str = str(exc)
        if "401" in err_str:
            error = "Client ID or Secret is incorrect. Check your app credentials in Kore.ai XO Platform."
        elif "botInfo" in err_str or ("400" in err_str and "error" in err_str.lower()):
            error = "Bot Display Name does not match your bot in Kore.ai XO Platform. Use the exact name shown in your bot settings."
        elif "connect" in err_str.lower() or "ConnectError" in type(exc).__name__:
            error = "Could not reach Kore.ai — check your Platform URL or network connection."
        else:
            error = f"Credential verification failed: {exc}"
        return templates.TemplateResponse("candidate_register.html", {
            "request": request, "portal": "candidate",
            "kore_platform_url": platform_url, "error": error,
        })

    now = datetime.now(timezone.utc).isoformat()
    reg = BotRegistration(
        bot_id=bot_id.strip(),
        bot_name=bot_name.strip(),
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        webhook_url=webhook_url.strip(),
        platform_url=platform_url.strip() or get_kore_platform_url(),
        registered_by=registered_by.strip(),
        registered_at=now,
        credential_verified_at=now,
        credential_status="verified",
    )
    save_bot_registration(reg)
    return RedirectResponse(url=f"/candidate/?bot_id={bot_id.strip()}", status_code=303)


@router.post("/register/{bot_id}/update")
async def update_registration(
    request: Request,
    bot_id: str,
    platform_url: str = Form(""),
    webhook_url: str = Form(""),
):
    reg = load_bot_registration(bot_id)
    if reg is None:
        return templates.TemplateResponse("candidate_register.html", {
            "request": request, "portal": "candidate",
            "kore_platform_url": get_kore_platform_url(),
            "error": f"Bot {bot_id} not registered.",
        })
    if platform_url.strip():
        reg.platform_url = platform_url.strip()
    if webhook_url.strip():
        reg.webhook_url = webhook_url.strip()
    save_bot_registration(reg)
    return RedirectResponse(url=f"/candidate/?bot_id={bot_id}", status_code=303)
```

- [ ] **Step 3: Update `GET /candidate/` to support `?bot_id=` query param**

Find the existing `@router.get("/")` handler. Add `bot_id: str = ""` as a query parameter. When `bot_id` is non-empty, attempt `load_bot_registration(bot_id)`. Pass it as `bot_registration=reg` (or `None`) to the template. If not found, pass `error="Bot not registered — please register your bot first."`.

- [ ] **Step 4: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 5: Commit**

```bash
git add src/governiq/candidate/routes.py
git commit -m "feat: candidate — /register GET/POST routes; /register/{id}/update; GET / gains ?bot_id lookup"
```

---

## Task 11: Candidate Submit Refactor

**Files:**
- Modify: `src/governiq/candidate/routes.py`

The existing `POST /candidate/submit` handler (around line 340) accepts inline credential fields. Read the handler from line 340 to ~527 first.

- [ ] **Step 1: Remove inline credential fields from the submit handler**

Replace the existing Form parameters for credentials:
```python
# REMOVE these Form params:
# bot_id: str = Form(""), bot_name: str = Form(""), client_id: str = Form(""),
# client_secret: str = Form(""), webhook_url: str = Form(""), platform_url: str = Form("")
```

Replace with:
```python
    bot_id: str = Form(...),          # hidden field, pre-filled from bot card
```

- [ ] **Step 2: Load credentials from registration**

After manifest lookup succeeds, add:

```python
    # Load bot registration — credentials come from persistent record
    from .registration import load_bot_registration, to_kore_credentials
    reg = load_bot_registration(bot_id)
    if reg is None:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request, "portal": "candidate",
            "available_manifests": available,
            "bot_registration": None,
            "error": f"Bot '{bot_id}' not registered. Please register your bot first.",
        })
    try:
        kore_creds = to_kore_credentials(reg)
    except ValueError as e:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request, "portal": "candidate",
            "available_manifests": available,
            "bot_registration": reg,
            "error": f"Credential error: {e}",
        })
    webhook_url = reg.webhook_url  # always from registration
```

Remove the old JWT block (lines ~442–456) that conditionally built `KoreCredentials` from inline form fields.

- [ ] **Step 3: Add `bot_id` field to the stub dict**

In the stub write block (around line 485–501), add:
```python
            "bot_id": bot_id,
```

- [ ] **Step 4: Remove `webhook_url` Form parameter**

The old handler accepted `webhook_url: str = Form("")`. Remove it — the value now always comes from `reg.webhook_url`.

- [ ] **Step 5: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/candidate/routes.py
git commit -m "feat: submit handler — load creds from bot registration; bot_id added to stub"
```

---

## Task 12: Admin Bots Route + Admin Settings Platform Route

**Files:**
- Modify: `src/governiq/admin/routes.py`

- [ ] **Step 1: Add imports to `admin/routes.py`**

At the top, ensure `from ..core.platform_config import get_kore_platform_url` is added. Also `from ..candidate.registration import list_bot_registrations, load_bot_registration, save_bot_registration, to_kore_credentials`.

- [ ] **Step 2: Add `GET /admin/bots` and `POST /admin/bots/{bot_id}/update`**

```python
@router.get("/bots")
async def admin_bots(request: Request, error: str = ""):
    regs = list_bot_registrations()
    results_dir = DATA_DIR / "results"
    counts: dict[str, int] = {}
    if results_dir.exists():
        for p in results_dir.glob("scorecard_*.json"):
            try:
                d = json.loads(p.read_text())
                bid = d.get("bot_id", "").strip()
                if bid:
                    counts[bid] = counts.get(bid, 0) + 1
            except Exception:
                continue
    return templates.TemplateResponse("admin_bots.html", {
        "request": request, "portal": "admin",
        "registrations": regs,
        "submission_counts": counts,
        "error": error,
    })


@router.post("/bots/{bot_id}/update")
async def admin_update_bot(
    request: Request,
    bot_id: str,
    platform_url: str = Form(""),
    webhook_url: str = Form(""),
    reverify: str = Form(""),
):
    reg = load_bot_registration(bot_id)
    if reg is None:
        return RedirectResponse(url="/admin/bots?error=Bot+not+found", status_code=303)
    if platform_url.strip():
        reg.platform_url = platform_url.strip()
    if webhook_url.strip():
        reg.webhook_url = webhook_url.strip()
    if reverify:
        from datetime import datetime, timezone
        from ..webhook.jwt_auth import get_kore_bearer_token
        try:
            creds = to_kore_credentials(reg)
            await get_kore_bearer_token(creds, max_retries=0)
            reg.credential_status = "verified"
            reg.credential_verified_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            save_bot_registration(reg)
            msg = str(exc)[:80].replace(" ", "+")
            return RedirectResponse(url=f"/admin/bots?error={msg}", status_code=303)
    save_bot_registration(reg)
    return RedirectResponse(url="/admin/bots", status_code=303)
```

- [ ] **Step 3: Add `POST /admin/settings/platform`**

```python
@router.post("/settings/platform")
async def admin_settings_platform(
    request: Request,
    kore_platform_url: str = Form(...),
):
    from ..core.platform_config import save_platform_config
    url = kore_platform_url.strip()
    if not url:
        return RedirectResponse(url="/admin/settings?saved=error_empty", status_code=303)
    save_platform_config(url)
    return RedirectResponse(url="/admin/settings?saved=platform", status_code=303)
```

Update the existing `GET /admin/settings` handler to add `"kore_platform_url": get_kore_platform_url()` to its template context.

- [ ] **Step 4: Add tests for the settings platform route**

Append to `tests/test_platform_config.py`:

```python
def test_post_settings_platform_saves_and_redirects(tmp_path, monkeypatch):
    import src.governiq.core.platform_config as pc
    monkeypatch.setattr(pc, "PLATFORM_CONFIG_PATH", tmp_path / "platform_config.json")
    from fastapi.testclient import TestClient
    from src.governiq.main import app
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/admin/settings/platform", data={"kore_platform_url": "https://custom.kore.ai/"})
    assert resp.status_code == 303
    assert "saved=platform" in resp.headers["location"]
    assert pc.get_kore_platform_url() == "https://custom.kore.ai/"


def test_post_settings_platform_rejects_empty_url():
    from fastapi.testclient import TestClient
    from src.governiq.main import app
    client = TestClient(app, follow_redirects=False)
    resp = client.post("/admin/settings/platform", data={"kore_platform_url": "   "})
    assert resp.status_code == 303
    assert "error_empty" in resp.headers["location"]
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_platform_config.py tests/test_bot_registration.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/governiq/admin/routes.py tests/test_platform_config.py
git commit -m "feat: admin — /admin/bots, /admin/bots/{id}/update, /admin/settings/platform routes"
```

---

## Task 13: Admin Restart — Credential Pre-fill from Registration

**Files:**
- Modify: `src/governiq/admin/routes.py`

- [ ] **Step 1: Update `restart_evaluation` Form signature**

Add four optional form fields:
```python
async def restart_evaluation(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
    mode: str = Form(...),
    kore_platform_url: str = Form(""),
    kore_client_id: str = Form(""),
    kore_client_secret: str = Form(""),
    kore_bot_name: str = Form(""),
):
```

- [ ] **Step 2: Add credential resolution logic**

Add after the lock check and before the `mode == "fresh"` branch:

```python
    # Credential resolution: explicit override > bot registration record > None (legacy)
    from ..webhook.jwt_auth import KoreCredentials, get_kore_bearer_token as _jwtgrant
    kore_creds = None
    if kore_client_id.strip() and kore_client_secret.strip():
        kore_creds = KoreCredentials(
            bot_id=original_stub.get("bot_id", ""),
            client_id=kore_client_id.strip(),
            client_secret=kore_client_secret.strip(),
            bot_name=kore_bot_name.strip(),
            platform_url=kore_platform_url.strip() or get_kore_platform_url(),
        )
    else:
        bot_id_on_stub = original_stub.get("bot_id", "").strip()
        if bot_id_on_stub:
            from ..candidate.registration import load_bot_registration, to_kore_credentials
            reg = load_bot_registration(bot_id_on_stub)
            if reg is not None:
                try:
                    kore_creds = to_kore_credentials(reg)
                except ValueError:
                    kore_creds = None

    # Pre-flight jwtgrant check when credentials are present
    if kore_creds is not None:
        try:
            await _jwtgrant(kore_creds, max_retries=0)
        except Exception as exc:
            err_str = str(exc)
            if "401" in err_str:
                msg = "Client ID or Secret is incorrect."
            elif "botInfo" in err_str:
                msg = "Bot Display Name does not match your bot in Kore.ai XO Platform."
            elif "connect" in err_str.lower():
                msg = "Could not reach Kore.ai — check Platform URL."
            else:
                msg = f"Credential check failed: {exc}"
            return JSONResponse({"error": msg}, status_code=400)
```

Pass `kore_creds` to `_run_evaluation_background` in place of the existing `kore_creds=None`.

- [ ] **Step 3: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 4: Commit**

```bash
git add src/governiq/admin/routes.py
git commit -m "feat: admin restart — credential pre-fill from bot registration; jwtgrant pre-flight check"
```

---

## Task 14: Observability Admin Routes

**Files:**
- Modify: `src/governiq/admin/routes.py`

Ensure `import asyncio` is at the top of `admin/routes.py`. `StreamingResponse` is imported from `fastapi.responses` — check if already present; add if not.

- [ ] **Step 1: Add UUID pattern constant (if not already present)**

```python
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
```

Note: `re` is already imported (`re.fullmatch(...)` is used in the restart handler). Add `_UUID_RE` as a module-level constant.

- [ ] **Step 2: Add the three observability routes**

```python
@router.get("/evaluation/{session_id}/log")
async def eval_log_json(request: Request, session_id: str):
    if not _UUID_RE.fullmatch(session_id):
        return JSONResponse({"error": "Invalid session ID"}, status_code=400)
    log_path = DATA_DIR / "logs" / f"eval_{session_id}.jsonl"
    events = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return JSONResponse({"events": events})


@router.get("/evaluation/{session_id}/conversation")
async def eval_conversation(request: Request, session_id: str):
    if not _UUID_RE.fullmatch(session_id):
        return JSONResponse({"error": "Invalid session ID"}, status_code=400)
    stub_path = DATA_DIR / "results" / f"scorecard_{session_id}.json"
    stub: dict = {}
    if stub_path.exists():
        try:
            stub = json.loads(stub_path.read_text())
        except Exception:
            pass
    return templates.TemplateResponse("admin_conversation.html", {
        "request": request, "portal": "admin",
        "session_id": session_id,
        "candidate_id": stub.get("candidate_id", "N/A"),
        "assessment_name": stub.get("assessment_name", "N/A"),
        "status": stub.get("status", "unknown"),
        "halt_reason": stub.get("halt_reason", None),
    })


@router.get("/evaluation/{session_id}/stream")
async def eval_stream(request: Request, session_id: str):
    if not _UUID_RE.fullmatch(session_id):
        return JSONResponse({"error": "Invalid session ID"}, status_code=400)

    log_path = DATA_DIR / "logs" / f"eval_{session_id}.jsonl"
    stub_path = DATA_DIR / "results" / f"scorecard_{session_id}.json"

    async def generate():
        # Wait up to 10 s for log file to appear (eval may have just started)
        waited = 0.0
        while not log_path.exists() and waited < 10.0:
            await asyncio.sleep(0.5)
            waited += 0.5

        offset = 0
        while True:
            if log_path.exists():
                try:
                    lines = log_path.read_text(encoding="utf-8").splitlines()
                    for line in lines[offset:]:
                        if line.strip():
                            yield f"data: {line}\n\n"
                    offset = len(lines)
                except Exception:
                    pass

            still_running = False
            if stub_path.exists():
                try:
                    stub = json.loads(stub_path.read_text())
                    still_running = stub.get("status") == "running"
                except Exception:
                    pass

            if not still_running:
                yield "event: done\ndata: {}\n\n"
                return

            await asyncio.sleep(0.5)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(generate(), media_type="text/event-stream")
```

- [ ] **Step 3: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 4: Commit**

```bash
git add src/governiq/admin/routes.py
git commit -m "feat: admin — SSE stream, conversation page, log JSON routes for eval observability"
```

---

## Task 15: api/routes.py — Replace Hardcoded Platform URL

**Files:**
- Modify: `src/governiq/api/routes.py`

- [ ] **Step 1: Find the hardcoded URL**

```
grep -n "KORE_PLATFORM_URL\|bots\.kore\.ai" src/governiq/api/routes.py
```

- [ ] **Step 2: Replace it**

Find the line with `os.environ.get("KORE_PLATFORM_URL", "https://bots.kore.ai")`. Replace with:

```python
from ..core.platform_config import get_kore_platform_url
...
platform_url = get_kore_platform_url()
```

Remove the `os.environ.get` call. If `os` is only imported for this call, check `api/routes.py` for other `os.` usages before removing the import.

- [ ] **Step 3: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 4: Commit**

```bash
git add src/governiq/api/routes.py
git commit -m "fix: api/routes — replace hardcoded KORE_PLATFORM_URL with get_kore_platform_url()"
```

---

## Task 16: base.html — Full CSS Design System

**Files:**
- Modify: `src/governiq/templates/base.html`

Read `base.html` in full before editing. Note:
- Where the `<style>` block is and what variables already exist.
- Which version of Lucide is loaded (check CDN script tag).
- Where `toggleVisibility` JS function is defined.
- Where the nav HTML lives (`.topnav` class or `<nav>` element).

- [ ] **Step 1: Add new CSS variables to existing theme blocks**

Find `html[data-theme="dark"]` and `html[data-theme="light"]` blocks. **Add** new variables inside each block (do not remove existing variables):

Dark block additions:
```css
  --bg:          #0f0f1a;
  --bg-surface:  rgba(255,255,255,.03);
  --card-bg:     rgba(255,255,255,.03);
  --card-border: rgba(255,255,255,.07);
  --text:        #e2e8f0;
  --text-secondary: #94a3b8;
  --muted:       #64748b;
  --input-bg:    rgba(255,255,255,.04);
  --primary:     #7c3aed;
  --accent:      #0891b2;
  --radius:      14px;
  --radius-sm:   8px;
  /* Backward-compat aliases (removed after all templates migrated) */
  --card:        var(--card-bg);
  --border:      var(--card-border);
  --bg-subtle:   var(--bg-surface);
  --nav-bg:      var(--bg);
```

Light block additions: same variables, light values (see spec section 2.1).

- [ ] **Step 2: Add component CSS classes**

Append the following to the `<style>` block in `base.html`. Use values verbatim from spec sections 2.2–2.10:

**2.2 Navigation** — `.nav`, `.nav-brand`, `.nav-logo`, `.nav-links`, `.nav-link`, `.nav-link.active`, `.nav-status-badge`

**2.3 Stat cards** — `.stats-grid`, `.stat-card`, `.stat-icon`, `.stat-val`, `.stat-label`

**2.4 Section headers** — `.section-icon`, `.section-icon.green`, `.section-icon.amber`, `.section-hdr`, `.section-title`, `.section-sub`

**2.5 Input-group** — `.input-group`, `.input-group:focus-within`, `.input-group .form-input`, `.toggle-visibility-btn`, `.toggle-visibility-btn:hover`

**2.6 Badges** — `.badge`, `.badge-dot`, `@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }`, `.badge.running`, `.badge.running .badge-dot`, `.badge.pass`, `.badge.fail`, `.badge.halted`

**2.7 Tables** — `.tbl th`, `.tbl td`, `.halt-reason`

**2.8 Action buttons** — `.btn-action`, `.btn-action.watch`, `.btn-action.review`, `.btn-action.restart`, `.btn-action.log`

**2.9 Score pill** — `.score-pill`, `.score-pill.pass`, `.score-pill.fail`

**2.10 Form sections** — `.form-section-hdr`, `.form-section-icon`, `.form-section-title`, `.form-section-sub`

Full CSS values for all these are in the spec (appended to `docs/superpowers/specs/2026-03-21-bot-pre-registration-design.md` under "Part 2").

- [ ] **Step 3: Update `toggleVisibility()` function**

Find existing `toggleVisibility` function. Replace body with:

```javascript
function toggleVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  btn.setAttribute('aria-label', isHidden ? 'Hide' : 'Show');
  btn.innerHTML = `<i data-lucide="${isHidden ? 'eye-off' : 'eye'}" style="width:15px;height:15px;stroke:currentColor;stroke-width:2;"></i>`;
  if (window.lucide) lucide.createIcons();
}
```

- [ ] **Step 4: Update nav HTML**

Find the existing nav/topnav HTML. Update class names to use `.nav`, `.nav-brand`, `.nav-logo`, `.nav-links`, `.nav-link`. Keep all existing href targets and link text — only class names change. Add `--nav-bg` alias to CSS variables (done in step 1) so `.topnav` still works if referenced in any existing template that isn't yet updated.

- [ ] **Step 5: Start dev server and visual check**

```
cd C:/Users/gvkir/Documents/EvalAutomaton
.venv/Scripts/python.exe -m uvicorn src.governiq.main:app --reload --port 8000
```
Open `http://localhost:8000/admin/` and `http://localhost:8000/candidate/`. Confirm:
- Dark theme background (`#0f0f1a`)
- Nav has gradient logo icon, correct link styling
- No broken CSS fallbacks on existing elements
- `toggleVisibility` works on any existing password field

- [ ] **Step 6: Run tests**

```
pytest tests/ -x -q --ignore=tests/test_integration_real_bots.py
```

- [ ] **Step 7: Commit**

```bash
git add src/governiq/templates/base.html
git commit -m "feat: base.html — CSS design system; dark-first theme vars; Lucide toggleVisibility"
```

---

## Task 17: Admin Templates

**Files:**
- Modify: `src/governiq/templates/admin_dashboard.html`
- Modify: `src/governiq/templates/admin_settings.html`
- Modify: `src/governiq/templates/admin_review.html` (additional markup work beyond Task 5)
- Modify: `src/governiq/templates/admin_compare.html`
- Modify: `src/governiq/templates/admin_manifest_list.html`
- Modify: `src/governiq/templates/admin_manifest_editor.html`
- Modify: `src/governiq/templates/admin_manifest_schema.html` (CSS only — no markup changes needed)
- Create: `src/governiq/templates/admin_bots.html`
- Create: `src/governiq/templates/admin_conversation.html`

Read each template before editing it.

**Alignment rules that apply to every template (per spec):**
1. All flex containers holding icons + text: `align-items: center`
2. All grid cells: `align-items: start` (unless single-line — then `center`)
3. All table cells: `vertical-align: middle` via `.tbl` — never override
4. All icon SVGs: explicit `width` and `height` attributes set (not CSS-only)
5. Input-group `.form-input`: no `border-radius` — parent handles it
6. Badges/pills: no `margin` inside — control from parent container
7. Action buttons in tables: wrapped in `<div class="actions" style="display:flex;gap:.4rem;align-items:center;">`

- [ ] **Step 1: `admin_dashboard.html` — stats grid + badge/button pattern**

Read `admin_dashboard.html`. Changes:
- Wrap stats cards in `<div class="stats-grid">`. Each card: `<div class="stat-card">` with `.stat-icon`, `.stat-val`, `.stat-label`.
- Table element: add `class="tbl"`.
- Status column: replace raw text with `<span class="badge {display_status}"><span class="badge-dot"></span>{label}</span>`.
- Below each status badge (in the same `<td>`): add halt-reason block in a flex column:
  ```html
  <div style="display:flex;flex-direction:column;align-items:flex-start;gap:.3rem;">
    <span class="badge ...">...</span>
    {% if sub.halt_reason %}
    <span class="halt-reason" title="{{ sub.halt_reason }}">{{ sub.halt_reason[:80] }}</span>
    {% endif %}
  </div>
  ```
- Action buttons: wrap all in `<div class="actions" style="display:flex;gap:.4rem;align-items:center;">`. Restyle existing Review/Restart links as `<a class="btn-action review">` / `<button class="btn-action restart">`.
- Add Watch Live button (shown only when `display_status == "running"`):
  ```html
  {% if sub.display_status == 'running' %}
  <a class="btn-action watch" href="/admin/evaluation/{{ sub.session_id }}/conversation" target="_blank">Watch Live</a>
  {% endif %}
  ```
- Add View Log button (always shown):
  ```html
  <a class="btn-action log" href="/admin/evaluation/{{ sub.session_id }}/conversation" target="_blank">View Log</a>
  ```
- The restart form submission already uses `fetch()` in some existing dashboard JS — if it doesn't, update it to: `fetch('/admin/evaluation/{id}/restart', {method:'POST', body: formData})`. On `status 400` with JSON body: display `data.error` inline. On redirect (303): `window.location.href = response.url`.

- [ ] **Step 2: `admin_settings.html` — add Platform Defaults section**

Read `admin_settings.html`. Add a new card (before the LLM config card) with:
- `.section-hdr` + `.section-icon` (globe SVG)
- A text input for `kore_platform_url` pre-filled from `{{ kore_platform_url }}`
- A Save button that POSTs to `/admin/settings/platform`
- Success message when `request.query_params.get('saved') == 'platform'`

- [ ] **Step 3: `admin_review.html` — section-icon headers**

Read `admin_review.html`. Update section headings (Score Breakdown, Task Results, Compliance) to use `.section-hdr` + `.section-icon` pattern. Variables are already safe-defaulted from Task 5. Ensure all fields render "Not available" with a fallback filter where needed.

- [ ] **Step 4: `admin_compare.html` — `.tbl` + new badge classes**

Read `admin_compare.html`. Add `class="tbl"` to any `<table>`. Update status badges to use `.badge` pattern.

- [ ] **Step 5: `admin_manifest_list.html` — `.tbl`**

Read `admin_manifest_list.html`. Add `class="tbl"` to the table element.

- [ ] **Step 6: `admin_manifest_editor.html` — form sections + input-group**

Read `admin_manifest_editor.html`. Add `.form-section-hdr` wrapper around logical form groups. Wrap any secret-style fields in `.input-group` + `.toggle-visibility-btn`.

- [ ] **Step 7: Create `admin_bots.html`**

```html
{% extends "base.html" %}
{% block title %}Bot Registry — GovernIQ Admin{% endblock %}
{% block content %}
<div style="max-width:900px;margin:0 auto;padding:1.5rem;">

  <div class="section-hdr">
    <div class="section-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
        <rect x="3" y="11" width="18" height="10" rx="2" ry="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
    </div>
    <div>
      <div class="section-title">Bot Registry</div>
      <div class="section-sub">{{ registrations|length }} registered bot(s)</div>
    </div>
  </div>

  {% if error %}
  <div style="background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.2);border-radius:8px;padding:.75rem 1rem;margin-bottom:1rem;color:#f87171;font-size:.82rem;">{{ error }}</div>
  {% endif %}

  <table class="tbl" style="width:100%;">
    <thead><tr>
      <th>Bot Name</th>
      <th>Bot ID</th>
      <th>Registered By</th>
      <th>Credential Status</th>
      <th>Last Verified</th>
      <th>Submissions</th>
      <th>Actions</th>
    </tr></thead>
    <tbody>
    {% for reg in registrations %}
    <tr>
      <td>{{ reg.bot_name }}</td>
      <td><code style="font-size:.75rem;">{{ reg.bot_id }}</code></td>
      <td>{{ reg.registered_by }}</td>
      <td>
        <span class="badge {% if reg.credential_status == 'verified' %}pass{% elif reg.credential_status == 'failed' %}fail{% else %}halted{% endif %}">
          <span class="badge-dot"></span>{{ reg.credential_status }}
        </span>
      </td>
      <td>{{ reg.credential_verified_at[:10] if reg.credential_verified_at else '—' }}</td>
      <td>{{ submission_counts.get(reg.bot_id, 0) }}</td>
      <td>
        <div class="actions" style="display:flex;gap:.4rem;align-items:center;">
          <form method="post" action="/admin/bots/{{ reg.bot_id }}/update" style="display:inline;">
            <input type="hidden" name="reverify" value="1">
            <button class="btn-action watch" type="submit">Re-verify</button>
          </form>
          <form method="post" action="/admin/bots/{{ reg.bot_id }}/update" style="display:inline;display:flex;gap:.3rem;align-items:center;">
            <input class="form-input" style="width:200px;font-size:.72rem;padding:.25rem .5rem;" type="url" name="platform_url" placeholder="Override Platform URL">
            <button class="btn-action log" type="submit">Save URL</button>
          </form>
        </div>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="7" style="text-align:center;color:var(--muted);padding:2rem;">No bots registered yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

</div>
{% endblock %}
```

- [ ] **Step 8: Create `admin_conversation.html`**

```html
{% extends "base.html" %}
{% block title %}Conversation — {{ session_id[:8] }} — GovernIQ Admin{% endblock %}
{% block content %}
<div style="max-width:800px;margin:0 auto;padding:1.5rem;">

  <div class="section-hdr" style="margin-bottom:1rem;">
    <div class="section-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    </div>
    <div>
      <div class="section-title">Conversation Log</div>
      <div class="section-sub">{{ assessment_name }} · {{ candidate_id }}</div>
    </div>
    <span class="badge {{ status }}" style="margin-left:auto;" id="status-badge">
      <span class="badge-dot"></span>{{ status }}
    </span>
  </div>

  <div id="timeline"
       style="display:flex;flex-direction:column;gap:.6rem;max-height:65vh;overflow-y:auto;padding:.5rem 0;border:1px solid var(--card-border);border-radius:var(--radius);padding:.75rem;">
    <!-- Events rendered by JS -->
  </div>

  <div id="done-banner"
       style="display:none;margin-top:1rem;background:rgba(5,150,105,.1);border:1px solid rgba(5,150,105,.25);border-radius:8px;padding:.75rem 1rem;color:#34d399;font-size:.85rem;">
    Evaluation complete.
  </div>

</div>

<script>
const sessionId = "{{ session_id }}";
const initialStatus = "{{ status }}";
const timeline = document.getElementById('timeline');
let autoScroll = true;

timeline.addEventListener('scroll', () => {
  autoScroll = timeline.scrollTop + timeline.clientHeight >= timeline.scrollHeight - 20;
});

function scrollBottom() {
  if (autoScroll) timeline.scrollTop = timeline.scrollHeight;
}

function renderEvent(ev) {
  const el = document.createElement('div');
  if (ev.type === 'webhook_turn_sent') {
    el.innerHTML = `<div style="display:flex;justify-content:flex-end;"><div style="background:rgba(37,99,235,.2);border:1px solid rgba(37,99,235,.15);border-radius:12px 12px 2px 12px;padding:.5rem .85rem;max-width:72%;font-size:.82rem;line-height:1.4;">${escHtml(ev.content)}</div></div>`;
  } else if (ev.type === 'webhook_turn_received') {
    el.innerHTML = `<div style="display:flex;"><div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:12px 12px 12px 2px;padding:.5rem .85rem;max-width:72%;font-size:.82rem;line-height:1.4;">${escHtml(ev.content)}</div></div>`;
  } else if (ev.type === 'task_started') {
    el.innerHTML = `<div style="text-align:center;color:var(--muted);font-size:.72rem;padding:.35rem 0;border-top:1px solid var(--card-border);border-bottom:1px solid var(--card-border);margin:.25rem 0;">── ${escHtml(ev.task_name)} ──</div>`;
  } else if (ev.type === 'task_completed') {
    el.innerHTML = `<div style="background:rgba(5,150,105,.08);border:1px solid rgba(5,150,105,.2);border-radius:6px;padding:.4rem .75rem;font-size:.78rem;color:#34d399;">✓ ${escHtml(ev.task_name)} passed</div>`;
  } else if (ev.type === 'task_failed') {
    el.innerHTML = `<div style="background:rgba(217,119,6,.08);border:1px solid rgba(217,119,6,.2);border-radius:6px;padding:.4rem .75rem;font-size:.78rem;color:#fbbf24;">✗ ${escHtml(ev.task_name)} failed: ${escHtml(ev.reason||'')}</div>`;
  } else if (ev.type === 'engine_error') {
    el.innerHTML = `<div style="background:rgba(220,38,38,.08);border:1px solid rgba(220,38,38,.2);border-radius:6px;padding:.4rem .75rem;font-size:.78rem;color:#f87171;">⚠ Halted: ${escHtml(ev.halt_reason||ev.error||'')}</div>`;
  } else if (ev.type === 'eval_completed') {
    el.innerHTML = `<div style="background:rgba(5,150,105,.12);border:1px solid rgba(5,150,105,.25);border-radius:8px;padding:.6rem 1rem;font-size:.88rem;color:#34d399;font-weight:700;">Evaluation complete · Score: ${ev.final_score}</div>`;
    document.getElementById('done-banner').style.display = 'block';
  } else if (ev.type === 'intent_classified') {
    el.innerHTML = `<div style="text-align:center;color:var(--muted);font-size:.66rem;">intent: ${escHtml(ev.intent)} (${escHtml(ev.method||'')})</div>`;
  } else if (ev.type === 'entity_injected') {
    el.innerHTML = `<div style="text-align:center;color:var(--muted);font-size:.66rem;">→ ${escHtml(ev.entity_key)} = &quot;${escHtml(String(ev.value))}&quot;</div>`;
  } else if (ev.type === 'llm_call') {
    el.innerHTML = `<details style="font-size:.68rem;color:var(--muted);padding:.2rem 0;"><summary style="cursor:pointer;">LLM ${escHtml(ev.purpose)}</summary><pre style="white-space:pre-wrap;margin:.25rem 0;font-size:.68rem;">${escHtml(ev.result||'')}</pre></details>`;
  } else if (ev.event) {
    // Old-schema entry (has 'event' key not 'type')
    el.innerHTML = `<div style="color:var(--muted);font-size:.68rem;padding:.1rem 0;">[${escHtml(ev.level||'info')}] ${escHtml(ev.event)}: ${escHtml(ev.detail||'')}</div>`;
  }
  if (el.innerHTML) { timeline.appendChild(el); scrollBottom(); }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

if (initialStatus === 'running') {
  const es = new EventSource(`/admin/evaluation/${sessionId}/stream`);
  es.onmessage = (e) => { try { renderEvent(JSON.parse(e.data)); } catch(x){} };
  es.addEventListener('done', () => {
    es.close();
    document.getElementById('done-banner').style.display = 'block';
    document.getElementById('status-badge').className = 'badge pass';
    document.getElementById('status-badge').innerHTML = '<span class="badge-dot"></span>completed';
  });
  es.onerror = () => {
    es.close();
    document.getElementById('done-banner').style.display = 'block';
  };
} else {
  fetch(`/admin/evaluation/${sessionId}/log`)
    .then(r => r.json())
    .then(data => { (data.events || []).forEach(renderEvent); });
}
</script>
{% endblock %}
```

- [ ] **Step 9: Visual check**

Start dev server. Open `/admin/`, `/admin/bots`, `/admin/settings`. Verify:
- All tables have `vertical-align: middle` on cells.
- Running eval rows show pulsing badge + Watch Live button.
- Platform Defaults card appears in settings.
- No alignment mismatches on any page.

- [ ] **Step 10: Commit**

```bash
git add src/governiq/templates/admin_*.html
git commit -m "feat: admin templates — design system, bots page, conversation log, Watch Live buttons"
```

---

## Task 18: Candidate Templates

**Files:**
- Create: `src/governiq/templates/candidate_register.html`
- Modify: `src/governiq/templates/candidate_submit.html`
- Modify: `src/governiq/templates/candidate_history.html`
- Modify: `src/governiq/templates/candidate_report.html`

Read each existing template before editing.

- [ ] **Step 1: Create `candidate_register.html` (Option C sectioned layout)**

```html
{% extends "base.html" %}
{% block title %}Register Your Bot — GovernIQ{% endblock %}
{% block content %}
<div style="max-width:540px;margin:2rem auto;padding:0 1rem;">

  <div class="section-hdr" style="margin-bottom:1.5rem;">
    <div class="section-icon">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
        <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>
      </svg>
    </div>
    <div>
      <div class="section-title">Register Your Bot</div>
      <div class="section-sub">Credentials are verified before saving. Registration is one-time per bot.</div>
    </div>
  </div>

  {% if error %}
  <div style="background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.2);border-radius:8px;padding:.75rem 1rem;margin-bottom:1.25rem;color:#f87171;font-size:.82rem;">{{ error }}</div>
  {% endif %}

  <div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:var(--radius);padding:1.5rem;">
    <form method="post" action="/candidate/register">

      <!-- Section: Kore.ai Credentials -->
      <div class="form-section-hdr">
        <div class="form-section-icon">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
        </div>
        <div>
          <div class="form-section-title">Kore.ai Credentials</div>
          <div class="form-section-sub">Required for live webhook testing</div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.85rem;">
        <div>
          <label class="form-label">BOT ID</label>
          <input class="form-input" type="text" name="bot_id" placeholder="st-xxxxxxx" required style="font-family:monospace;font-size:.82rem;">
        </div>
        <div>
          <label class="form-label">BOT DISPLAY NAME</label>
          <input class="form-input" type="text" name="bot_name" placeholder="TravelBot" required>
        </div>
      </div>

      <div style="margin-bottom:.85rem;">
        <label class="form-label">CLIENT ID</label>
        <input class="form-input" type="text" name="client_id" id="client_id" placeholder="cs-xxxxxxx" required style="font-family:monospace;font-size:.82rem;">
      </div>

      <div style="margin-bottom:.85rem;">
        <label class="form-label">CLIENT SECRET</label>
        <div class="input-group">
          <input class="form-input" type="password" name="client_secret" id="client_secret" required style="font-family:monospace;font-size:.82rem;">
          <button type="button" class="toggle-visibility-btn" onclick="toggleVisibility('client_secret', this)" aria-label="Show">
            <i data-lucide="eye" style="width:15px;height:15px;stroke:currentColor;stroke-width:2;"></i>
          </button>
        </div>
        <div class="form-hint">Used to sign authentication tokens.</div>
      </div>

      <!-- Section: Platform Connection -->
      <div class="form-section-hdr" style="margin-top:1.25rem;">
        <div class="form-section-icon" style="background:var(--accent);">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
            <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
        </div>
        <div>
          <div class="form-section-title">Platform Connection</div>
          <div class="form-section-sub">Where to reach your bot</div>
        </div>
      </div>

      <div style="margin-bottom:.85rem;">
        <label class="form-label">WEBHOOK URL</label>
        <input class="form-input" type="url" name="webhook_url" placeholder="https://platform.kore.ai/hooks/..." required>
      </div>

      <div style="margin-bottom:1.25rem;">
        <label class="form-label">PLATFORM URL <span style="color:var(--muted);font-weight:400;text-transform:none;">(admin-configurable default)</span></label>
        <input class="form-input" type="url" name="platform_url" value="{{ kore_platform_url }}">
        <div class="form-hint">The Kore.ai hostname. Pre-filled from admin settings — edit only if your account uses a different URL.</div>
      </div>

      <input type="hidden" name="registered_by" value="">

      <button class="btn btn-primary" type="submit" style="width:100%;">Verify &amp; Register Bot</button>
    </form>
  </div>

  <div style="margin-top:1rem;text-align:center;font-size:.78rem;color:var(--muted);">
    Already registered? <a href="/candidate/" style="color:var(--primary);">Go to submission →</a>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 2: Update `candidate_submit.html` — Bot Card + lookup**

Read `candidate_submit.html`. Replace the inline credential input block with:

When `bot_registration` is not None (resolved from `?bot_id=`):
```html
<div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:var(--radius);padding:1.25rem;margin-bottom:1.25rem;">
  <div class="section-hdr" style="margin-bottom:.75rem;">
    <div class="section-icon green">
      <svg width="16" height="16" ...bot icon...></svg>
    </div>
    <div>
      <div class="section-title">{{ bot_registration.bot_name }}</div>
      <div class="section-sub"><code>{{ bot_registration.bot_id }}</code> · {{ bot_registration.webhook_url }}</div>
    </div>
    <span class="badge {% if bot_registration.credential_status == 'verified' %}pass{% else %}halted{% endif %}" style="margin-left:auto;">
      <span class="badge-dot"></span>{{ bot_registration.credential_status }}
    </span>
  </div>
  <input type="hidden" name="bot_id" value="{{ bot_registration.bot_id }}">
</div>
<div style="margin-bottom:.75rem;font-size:.78rem;">
  <a href="/candidate/register" style="color:var(--muted);">Register a different bot →</a>
</div>
```

When `bot_registration` is None:
```html
<div style="background:var(--card-bg);border:1px solid var(--card-border);border-radius:var(--radius);padding:1.25rem;margin-bottom:1.25rem;">
  <div class="section-hdr" style="margin-bottom:.75rem;">
    <div class="section-icon amber"><svg ...search icon...></svg></div>
    <div><div class="section-title">Find Your Bot</div></div>
  </div>
  {% if error %}
  <div style="color:#f87171;font-size:.78rem;margin-bottom:.75rem;">{{ error }}</div>
  {% endif %}
  <form method="get" action="/candidate/" style="display:flex;gap:.5rem;align-items:center;">
    <input class="form-input" style="flex:1;" type="text" name="bot_id" placeholder="st-xxxxxxx" required>
    <button class="btn btn-primary" type="submit">Find</button>
  </form>
  <div style="margin-top:.75rem;font-size:.78rem;color:var(--muted);">
    First time? <a href="/candidate/register" style="color:var(--primary);">Register your bot →</a>
  </div>
</div>
```

Remove any existing `webhook_url`, `platform_url`, `client_id`, `client_secret`, `bot_id`, `bot_name` form fields from the submit form.

- [ ] **Step 3: `candidate_history.html`**

Read `candidate_history.html`. Add `class="tbl"` to the table. Update status cells to use `.badge` pattern. Update score cells to use `.score-pill pass|fail`.

- [ ] **Step 4: `candidate_report.html`**

Read `candidate_report.html`. Update:
- Score display: large number in a coloured span (`color:#34d399` if pass, `#f87171` if fail).
- Pass/fail banner: `<div class="badge pass|fail" style="...">` at top.
- Per-pipeline breakdown: use `.score-pill` for each pipeline score.

- [ ] **Step 5: Visual check**

Open `/candidate/register` and `/candidate/`. Verify:
- Registration form has two sections (Credentials + Platform Connection)
- `client_secret` has inline eye-toggle that works
- Bot Card renders correctly when `?bot_id=` resolves to a registration

- [ ] **Step 6: Commit**

```bash
git add src/governiq/templates/candidate_*.html
git commit -m "feat: candidate templates — register form, bot card, history/report design updates"
```

---

## Task 19: Remaining Templates

**Files:**
- Modify: `src/governiq/templates/landing.html`
- Modify: `src/governiq/templates/error.html` (CSS only)
- Modify: `src/governiq/templates/how_it_works.html` (CSS only)

- [ ] **Step 1: Verify `error.html` and `how_it_works.html` inherit correctly**

Start dev server. Manually navigate to a 404 URL (e.g. `/admin/notfound`) to trigger `error.html`. Open `/how_it_works`. Confirm both render correctly with the dark theme from `base.html` — no structural changes needed.

- [ ] **Step 2: Update `landing.html`**

Read `landing.html`. Update:
- Body/hero background: use `var(--bg)` (dark).
- Feature cards: use `var(--card-bg)` / `var(--card-border)`.
- Any CTA buttons: ensure they use `.btn btn-primary`.
- Any stats: use `.stat-card` / `.stat-val` pattern.
- Remove any inline `background: #fff` or light-mode hardcoded colours.

- [ ] **Step 3: Visual check all three pages**

Open `/`, `/how_it_works`, trigger `/nonexistent` for error page. Confirm:
- All three show dark background.
- No grey-box fallback CSS on any element.
- Typography is consistent with the rest of the app.

- [ ] **Step 4: Commit**

```bash
git add src/governiq/templates/landing.html src/governiq/templates/error.html src/governiq/templates/how_it_works.html
git commit -m "feat: landing/error/how_it_works — inherit dark design system from updated base.html"
```

---

## Task 20: Final Test Run + Verification

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -v --ignore=tests/test_integration_real_bots.py
```
Expected: all tests PASS. Fix any failures before proceeding.

- [ ] **Step 2: Run the stabilisation and scorecard field tests**

```
pytest tests/test_stabilisation.py tests/test_scorecard_fields.py tests/test_resume.py -v
```
These exercise the restart/resume flow — most relevant to the bug fixes.

- [ ] **Step 3: Verify `data/bot_registrations/` is gitignored**

```bash
git check-ignore -v data/
```
Expected: `data/` is ignored. If `bot_registrations/` somehow is not covered, add `data/bot_registrations/` to `.gitignore`.

- [ ] **Step 4: Final commit**

```bash
git add src/governiq/ tests/ docs/
git commit -m "test: final sprint test pass — all 20 tasks verified"
```

---

## Route Table

| Method | Path | Handler file | New/Modified |
|--------|------|-------------|-------------|
| GET | `/candidate/register` | `candidate/routes.py` | New |
| POST | `/candidate/register` | `candidate/routes.py` | New |
| POST | `/candidate/register/{bot_id}/update` | `candidate/routes.py` | New |
| GET | `/candidate/` | `candidate/routes.py` | Modified (`?bot_id` param added) |
| POST | `/candidate/submit` | `candidate/routes.py` | Modified (inline creds removed) |
| GET | `/admin/bots` | `admin/routes.py` | New |
| POST | `/admin/bots/{bot_id}/update` | `admin/routes.py` | New |
| POST | `/admin/settings/platform` | `admin/routes.py` | New |
| GET | `/admin/evaluation/{id}/stream` | `admin/routes.py` | New |
| GET | `/admin/evaluation/{id}/conversation` | `admin/routes.py` | New |
| GET | `/admin/evaluation/{id}/log` | `admin/routes.py` | New |
| POST | `/admin/evaluation/{id}/restart` | `admin/routes.py` | Modified (manifest-first + creds) |
| GET | `/admin/review/{id}` | `admin/routes.py` | Modified (defensive context) |
