# EvalAutomaton Stabilisation Sprint — Design Spec
**Date:** 2026-03-20
**Status:** Approved for implementation
**Scope:** Bug fixes, admin visibility & control, live evaluation log, API error halting, UI polish, health caching, manifest scoring weights

---

## 1. Problem Statement

Three silent crashes are preventing evaluations from completing. Because the admin dashboard filters out crashed submissions, admins have no visibility that anything went wrong. There is no way to re-run a failed evaluation, no way to watch an evaluation in progress, and no way to verify that an API key works after entering it. Additionally, the health endpoint burns LLM rate-limit quota by making live API calls every 30 seconds, and manifest-declared scoring weights are silently ignored by the engine.

---

## 2. Goals

1. Fix all crashes so evaluations complete reliably
2. Give admins full visibility of every submission regardless of status
3. Give admins manual re-run controls (Start Fresh and Resume)
4. Halt and flag evaluations when the LLM API returns rate-limit or auth errors
5. Show a real-time, collapsible log panel per evaluation as evidence
6. Fix white-on-white dropdown text and add API key show/hide with inline verification
7. Cache the health endpoint LLM check to stop burning rate-limit quota
8. Respect manifest `scoring_config` weights instead of hardcoded 80/10/10

---

## 3. Non-Goals (deferred to next sprint)

- Admin authentication / authorisation
- State seeding transparency in scoring
- Plagiarism failure alerting
- Multi-server / horizontal scale support
- Multi-session live log panel (show only most-recently-activated session)

---

## 4. Architecture Overview

The sprint is structured in six dependency-ordered layers. Each layer can be shipped independently once its dependencies are complete. CSS/UI fixes are fully independent and can be merged at any point.

```
Layer 0 — Storage Foundation
    ↓
Layer 1 — Crash Fixes + Message Normaliser + CSS
    ↓
Layer 2 — Engine Stability (Halt Mechanism)
    ↓
Layer 3 — Admin Control Surface
    ↓
Layer 4 — Live Log Panel
    ↓
Layer 5 — Scoring + Health Caching
```

---

## 5. Layer 0 — Storage Foundation

### 5.1 Enriched Stub Schema

The submission stub written immediately on candidate submit is the shared data contract for all other features. It must be enriched from the current minimal shape to:

```json
{
  "session_id": "uuid",
  "status": "running | completed | halted | error",
  "candidate_id": "string",
  "manifest_id": "string",
  "assessment_name": "string",
  "webhook_url": "string",
  "submitted_at": "ISO UTC",
  "completed_tasks": [],
  "halt_reason": null,
  "halted_on_task": null,
  "halted_at": null,
  "parent_session_id": null,
  "log_file": "data/logs/eval_{session_id}.jsonl",
  "error": null
}
```

All fields must be written at stub creation time (submission). `completed_tasks`, `halt_reason`, `halted_on_task`, `halted_at` are updated during execution.

**File:** `src/governiq/candidate/routes.py`

### 5.2 ZIP Storage

Uploaded bot export files must be preserved for re-runs.

- On submission: copy uploaded file to `data/uploads/{session_id}/bot_export.zip` (or `.json`)
- Cleanup: remove uploads older than 7 days. Run cleanup at startup and on each submission.
- If ZIP missing at re-run time: return error "Original upload not found — re-upload required"

**File:** `src/governiq/candidate/routes.py`

### 5.3 Lock Files

Prevents concurrent re-runs on the same session.

- Create `data/locks/{session_id}.lock` at start of background task: `{"started_at": "ISO", "pid": int}`
- Delete in `finally` block — always deleted on any terminal state (completed, halted, error, crash)
- Stale lock: if `started_at` > 10 minutes ago, treat as abandoned and allow re-run

**File:** `src/governiq/candidate/routes.py`

### 5.4 JSONL Log Format

Each evaluation writes a structured log to `data/logs/eval_{session_id}.jsonl`.

Each line is a JSON object:
```json
{"ts": "ISO", "task_id": "task1", "level": "info|warn|error", "event": "event_name", "detail": "human string", "raw": {}}
```

Named events: `task_start`, `warm_up`, `bot_message`, `user_message`, `intent_classified`, `check_pass`, `check_fail`, `state_seeded`, `evaluation_halted`, `task_complete`

Max 10,000 lines per file (oldest entries truncated if exceeded). Files older than 30 days cleaned up at startup.

**New file:** `src/governiq/core/eval_logger.py`

---

## 6. Layer 1 — Crash Fixes + Message Normaliser + CSS

### 6.1 value_pool Normalisation

**Root cause:** `random.choice()` called on a dict when manifest `value_pool` is authored as a JSON object instead of a JSON array.

**Fix location:** Manifest load time (not at selection time), so all downstream readers get clean data.

- In the manifest loader, after parsing JSON, walk all tasks → entities → if `value_pool` is `dict`, convert `dict.values()` to `list` and log `WARNING: MD-VPOOL: task {id} entity {key} value_pool is dict, auto-converted. Fix manifest.`
- Same normalisation applied in manifest save-time validation (see 6.4)

**File:** manifest loader in `src/governiq/core/` (wherever manifests are parsed into task objects)

### 6.2 Message Normaliser

**Root cause:** Kore.ai webhook responses can contain structured message objects (dicts) instead of plain strings. The driver assumes strings when joining messages.

**New file:** `src/governiq/webhook/message_normaliser.py`

```
extract_text(message: str | dict) -> str
  - str → return as-is
  - dict with "val" → str(message["val"])
  - dict with "text" → str(message["text"])
  - dict with "payload.text" → str(message["payload"]["text"])
  - dict with type="template" → "[template message]"
  - fallback → str(message)

normalise_messages(messages: list) -> tuple[list[str], list[dict]]
  Returns (text_list, raw_list)
  text_list: for display/joining/LLM classification
  raw_list: original message objects for evidence storage
```

**File:** `src/governiq/webhook/driver.py` — import and use `normalise_messages()` at all message-joining points.

### 6.3 Template Guards

**Root cause:** Jinja2 templates access `s.overall_score` on stubs that don't have this key.

- `candidate_history.html`: wrap score display in `{% if s.overall_score is defined and s.overall_score is not none %}`; show status badge for stubs without a score
- Admin submission list template: same guard; show enriched status badge instead of score for non-completed records

**Files:** `src/governiq/templates/candidate_history.html`, admin submission list template

### 6.4 Manifest Save-Time Validation

A new `validate_manifest(data: dict) -> dict` function checks:
- All `value_pool` fields are lists (warning if dict)
- `scoring_config` weights sum to ~1.0 within tolerance 0.01 (warning if not)
- `pass_threshold` in [0.5, 1.0] (error if outside range)
- Required top-level fields present: `manifest_id`, `tasks`, `scoring_config`

Returns `{"valid": bool, "errors": [...], "warnings": [...]}`.

The manifest save endpoint (`_save_manifest`) calls this before writing:
- Errors → block save, return 400 with error list
- Warnings only → save proceeds, warnings shown as flash messages in UI

**File:** `src/governiq/admin/routes.py`

### 6.5 CSS Fixes

**Dropdown white-on-white:**
```css
select, select option {
  color: #1e293b;
  background-color: #ffffff;
}
```
Applied globally. Audit all templates for `<select>` elements to confirm coverage.

**API key show/hide toggle:**
- Add eye icon button next to all `type="password"` / API key fields
- JS toggles `input.type` between `"password"` and `"text"`
- Icon changes between eye-open and eye-closed state
- No server-side changes needed

**Files:** `src/governiq/templates/base.html`, admin settings template

---

## 7. Layer 2 — Engine Stability (Halt Mechanism)

### 7.1 EvaluationHaltedError

**New file:** `src/governiq/core/exceptions.py`

```python
class EvaluationHaltedError(Exception):
    def __init__(self, reason: str, task_id: str, retriable: bool = True):
        self.reason = reason
        self.task_id = task_id
        self.retriable = retriable  # False for 401 (bad key), True for 429 (rate limit)
```

### 7.2 LLM Retry-Once then Halt

**Current behaviour:** LLM call fails → log warning → fall back to rule-based responses → continue.
**New behaviour:** LLM call fails → retry once after 8 seconds → if fails again → raise `EvaluationHaltedError`.

- 401 Unauthorized: do NOT retry — raise immediately with `retriable=False`
- 429 Too Many Requests: retry once, then raise with `retriable=True`
- Other 5xx: retry once, then raise with `retriable=True`
- Rule-based fallback is removed from the LLM generation path (classification fallback retained for non-critical use only)

**File:** `src/governiq/webhook/driver.py`

### 7.3 Halt Handler in Engine

`_run_webhook_pipeline` wraps task execution in `try/except EvaluationHaltedError`:

On catch:
1. Save `RuntimeContext` checkpoint to disk
2. Update stub file: `status="halted"`, `halt_reason=e.reason`, `halted_on_task=e.task_id`, `halted_at=utcnow()`, `completed_tasks=context.completed_tasks`
3. Delete lock file
4. Return gracefully (do not propagate)

`_run_evaluation_background` in `candidate/routes.py`:
- Add specific `except EvaluationHaltedError` before the broad `except Exception`
- Broad `except Exception` still handles unexpected crashes → `status="error"`
- `finally` block always deletes lock file

**Files:** `src/governiq/core/engine.py`, `src/governiq/candidate/routes.py`

### 7.4 EvalLogger Wiring

`EvalLogger` instance created in `_run_evaluation_background`, passed into engine and driver.

Engine logs: `task_start`, `task_complete`, `state_seeded`, `evaluation_halted`
Driver logs: `warm_up`, `bot_message` (with raw payload), `user_message`, `intent_classified`, `check_pass`, `check_fail`

**Files:** `src/governiq/core/engine.py`, `src/governiq/webhook/driver.py`

---

## 8. Layer 3 — Admin Control Surface

### 8.1 Show All Submissions

`_load_all_evaluations()` loads ALL scorecards regardless of status. Replaces the current filter that hides `running` and `error` records.

New helper `_enrich_submission(data: dict) -> dict` adds computed display fields:
- `display_status`: `"completed" | "running" | "halted" | "error" | "stale"`
  Stale = status is `"running"` and `submitted_at` > 15 minutes ago
- `can_resume`: `True` if status in `("halted", "error")` AND RuntimeContext file exists and is valid JSON AND no active lock
- `can_start_fresh`: `True` for all non-running submissions AND ZIP exists in `data/uploads/{session_id}/`
- `zip_available`: `True` if `data/uploads/{session_id}/` contains the export file
- `has_active_lock`: `True` if lock file exists and not stale
- Safe defaults for all optional fields (`overall_score=None`, `candidate_id="unknown"`, etc.)

**File:** `src/governiq/admin/routes.py`

### 8.2 Admin Submission List Template

Status badge colours:
| Status | Colour | Icon |
|--------|--------|------|
| completed | green | ✓ |
| running | blue | spinner |
| halted | amber | ⚠ + halt_reason tooltip |
| error | red | ✗ |
| stale | grey | clock icon |

Re-run buttons:
- **Start Fresh**: shown when `can_start_fresh=True`; disabled with tooltip "Re-upload required" when `zip_available=False`
- **Resume**: shown when `can_resume=True`; hidden otherwise
- Both disabled (greyed) when `has_active_lock=True` with tooltip "Evaluation is currently running"

Re-runs grouped under parent: new session rows appear as indented sub-rows under the original submission (linked via `parent_session_id`).

**File:** admin submission list template

### 8.3 Re-Run Endpoint

```
POST /admin/evaluation/{session_id}/restart?mode=fresh|resume
```

Guards:
- If `has_active_lock` → 409 "Evaluation still running, please wait"
- mode=fresh + ZIP missing → 400 "Original upload not found — re-upload required"
- mode=resume + RuntimeContext invalid → 400 "Checkpoint not found or corrupt — use Start Fresh"

mode=fresh:
- Generate new `session_id`
- Write enriched stub with all original metadata + `parent_session_id=original_session_id`
- Launch background task from scratch

mode=resume:
- Generate new `session_id` (preserves evidence chain)
- Write enriched stub with `parent_session_id=original_session_id` + `completed_tasks` from original
- Launch background task with `resume=True` and original RuntimeContext loaded

**File:** `src/governiq/admin/routes.py`

### 8.4 Inline API Key Verification

After `save_llm_settings` saves config, immediately probe the LLM provider (reuse the health check LLM probe function, not the full health endpoint).

Pass result to template redirect as query param: `?verified=1` (success) or `?verified=0&reason=...` (failure).

Settings page renders a flash banner: green "API key verified — {provider} connected" or red "API key invalid — {reason}".

**File:** `src/governiq/admin/routes.py`, admin settings template

---

## 9. Layer 4 — Live Log Panel

### 9.1 Log Streaming Endpoint

```
GET /api/v1/logs/{session_id}?offset=0
```

Response:
```json
{
  "entries": [{"ts": "...", "task_id": "...", "level": "...", "event": "...", "detail": "...", "raw": {}}],
  "next_offset": 42,
  "done": true
}
```

- Opens `data/logs/eval_{session_id}.jsonl`, skips first `offset` lines, returns remaining
- `done=true` if submission status is in terminal state (`completed`, `error`, `halted`)
- If file doesn't exist yet: `{"entries": [], "next_offset": 0, "done": false}`

**File:** `src/governiq/api/routes.py`

### 9.2 Frontend Log Panel

A floating, collapsible panel rendered in the admin base template (available on all admin pages).

**Structure:**
```
┌─────────────────────────────────────────────┐
│ Evaluation Log — abc12345...  [─] [□] [✕]  │
├─────────────────────────────────────────────┤
│ ▶ task1 — Welcome Message                   │
│   [info]  08:17:11  Warm-up probe sent      │
│   [bot]   08:17:12  "Hello, how can I help?"│
│   [user]  08:17:13  "Book a flight to Rome" │
│   [pass]  08:17:14  Welcome intent detected │
│ ▶ task2 — Create Booking                    │
│   ...                                       │
└─────────────────────────────────────────────┘
```

**Behaviour:**
- Fixed position, bottom-right, z-index above page content
- Minimise: collapses to header bar only
- Maximise: expands to ~60% viewport height
- Panel state (minimised/maximised) persisted to `localStorage`
- Active session_id stored in `sessionStorage`
- Polls `GET /api/v1/logs/{session_id}?offset=N` every 3 seconds
- Auto-scrolls to bottom unless user has manually scrolled up
- Stops polling when `done=true`
- Shows most recently activated session; no multi-session switching in this sprint

**Colour coding:**
| Event type | Colour |
|-----------|--------|
| info / task_start / warm_up | grey |
| bot_message | blue |
| user_message | green |
| check_pass / task_complete | green |
| check_fail / evaluation_halted | red |
| warn / state_seeded | amber |

**File:** `src/governiq/templates/base.html` (admin section only)

### 9.3 Evidence Integration

On evaluation completion (inside `engine.py`):
- Read `data/logs/eval_{session_id}.jsonl`
- Group entries by `task_id`
- For each task, append conversation transcript summary to `task_score.evidence_cards`
- Full JSONL file retained separately for raw access
- `log_file` field in scorecard references the JSONL path

**File:** `src/governiq/core/engine.py`

---

## 10. Layer 5 — Scoring + Health

### 10.1 Health Endpoint Caching

**Current problem:** Every health poll makes a live HTTP call to the LLM provider. With 30-second browser polling, this burns 120 LLM API calls per hour per open tab.

**Fix:** Module-level cache dict in the health handler:
```python
_health_cache: dict[str, dict] = {}  # key → {"result": {...}, "cached_at": datetime}
```

Cache key: `f"{provider}:{base_url}:{model}"` — invalidated automatically when admin switches provider.

TTL: 25 seconds for LLM check, 300 seconds (5 minutes) for storage check.

**401 fix:** `response.status_code == 401` → `status="failing"`, `message="API key invalid or unauthorized"`. Previously treated as "ok" because `< 500`.

**File:** `src/governiq/api/routes.py`

### 10.2 Manifest Scoring Weights

**Current problem:** `Scorecard.overall_score` uses hardcoded 80/10/10 weights regardless of manifest `scoring_config`.

**Fix:** `Scorecard.__init__` accepts `scoring_config: dict | None = None`.

If provided:
1. Extract `webhook_functional_weight`, `compliance_weight`, `faq_weight`, `pass_threshold`
2. Validate: each weight in [0, 1], pass_threshold in [0.5, 1.0]
3. Normalise: if weights don't sum to 1.0 (within tolerance 0.01), rescale proportionally
4. Store as instance attributes

`overall_score` property uses instance weight attributes.

If `scoring_config=None` (historical records loaded from disk): use legacy hardcoded weights — **historical scores are never re-computed**.

**Weight redistribution:** If a pipeline is unused (e.g., no FAQ tasks → `faq_score=None`), its weight is redistributed proportionally to the remaining pipelines. This logic lives in `engine.py` when constructing the Scorecard, not in `scoring.py`.

**File:** `src/governiq/core/scoring.py`, `src/governiq/core/engine.py`

---

## 11. New Files Summary

| File | Purpose |
|------|---------|
| `src/governiq/webhook/message_normaliser.py` | Safe extraction of text from all Kore.ai message types |
| `src/governiq/core/eval_logger.py` | Structured JSONL logger per evaluation session |
| `src/governiq/core/exceptions.py` | `EvaluationHaltedError` with reason, task_id, retriable flag |

---

## 12. Modified Files Summary

| File | Changes |
|------|---------|
| `src/governiq/candidate/routes.py` | Enrich stub, ZIP storage, lock file lifecycle, halt handler |
| `src/governiq/core/engine.py` | Halt handler, EvalLogger wiring, scoring_config pass-through, weight redistribution, evidence embedding |
| `src/governiq/webhook/driver.py` | Use message_normaliser, retry-once + raise EvaluationHaltedError, EvalLogger wiring |
| `src/governiq/core/scoring.py` | scoring_config parameter, instance weight attributes, normalisation |
| `src/governiq/api/routes.py` | Health cache + 401 fix, GET /api/v1/logs/{session_id} endpoint |
| `src/governiq/admin/routes.py` | Show all statuses, _enrich_submission, restart endpoint, inline key verify, manifest validation |
| `src/governiq/templates/candidate_history.html` | Template guards for overall_score |
| `src/governiq/templates/base.html` | CSS select fix, live log panel component |
| Admin submission list template | Status badges, re-run buttons, parent/child grouping |
| Admin settings template | Show/hide toggle, inline verification flash |

---

## 13. Test Plan

| Phase | Test | What it verifies |
|-------|------|-----------------|
| 0 | test_stub_schema | Stub has all new fields after submission |
| 0 | test_zip_storage | ZIP saved to data/uploads/{session_id}/ |
| 0 | test_lock_lifecycle | Lock created on start, deleted on terminal state |
| 1 | test_value_pool_normalisation | Dict value_pool converted to list at load time |
| 1 | test_message_normaliser_all_types | All Kore.ai types return correct text + raw |
| 1 | test_template_guard_error_stub | Render history with error stub — no UndefinedError |
| 2 | test_halt_on_429_after_retry | 429 twice → EvaluationHaltedError raised |
| 2 | test_retry_success_on_first_429 | 429 once then 200 → no halt |
| 2 | test_halt_writes_checkpoint | Halt → status="halted" in stub + RuntimeContext saved |
| 2 | test_eval_logger_writes_jsonl | Log events → valid JSONL file written |
| 3 | test_admin_shows_all_statuses | All status variants appear in _load_all_evaluations |
| 3 | test_enrich_can_resume | RuntimeContext present → can_resume=True; missing → False |
| 3 | test_restart_fresh | POST restart?mode=fresh creates new session |
| 3 | test_restart_blocked_by_lock | Active lock → 409 |
| 4 | test_log_endpoint_offset | Poll with offset=N returns only new entries |
| 4 | test_log_endpoint_done | Terminal status → done=true |
| 5 | test_health_cache_hit | Two polls within TTL → LLM probed once |
| 5 | test_health_401_failing | 401 response → status="failing" |
| 5 | test_scoring_manifest_weights | Scorecard uses manifest weights not hardcoded |
| 5 | test_scoring_normalises_weights | Weights not summing to 1.0 → normalised |
| 5 | test_manifest_validation_bad_threshold | pass_threshold=0.1 → error returned |

---

## 14. Known Limitations (Next Sprint)

- No admin authentication — any visitor can trigger re-runs
- State seeding still masks CREATE task failures silently
- Plagiarism detection failures are silently swallowed
- Log panel shows only the most-recently-activated session
- All storage is local filesystem — not suitable for horizontal scaling
- RuntimeContext partial-write corruption not detected beyond valid JSON check
