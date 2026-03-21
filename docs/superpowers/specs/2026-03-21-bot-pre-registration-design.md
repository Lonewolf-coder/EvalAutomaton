# Bot Pre-Registration + Credential Hardening — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Context:** EvalAutomaton / GovernIQ Universal Evaluation Platform

---

## Problem Statement

The current candidate submission form collects Kore.ai bot credentials (bot_id, client_id, client_secret, bot_name, webhook_url) inline at submission time. This causes four problems:

1. **Admin restarts break silently** — the restart endpoint passes `kore_creds=None`, so all JWT-protected bots halt with 401 immediately after restart.
2. **Re-submitters re-enter credentials every attempt** — no persistence between certification attempts.
3. **No credential validation at submit time** — invalid credentials surface as silent analytics failures minutes into evaluation.
4. **bot_name is optional** — jwtgrant exchanges (analytics, debug logs) fail silently when it is missing. For certification, analytics are mandatory.

---

## Goals

- Candidates register their bot once with full credential validation before submitting.
- Credentials persist so admin restarts work without re-entry.
- `bot_name`, `bot_id`, `client_id`, `client_secret`, `webhook_url`, and `platform_url` are all mandatory at registration.
- Both candidates and admins can update `platform_url` if the Kore.ai endpoint changes.
- Admin can always override or paste credentials at restart time (for legacy submissions or credential rotation).

---

## Non-Goals

- No encryption of stored credentials (internal on-prem platform, documented risk).
- No multi-bot support per candidate (one active bot registration per `bot_id`).
- No changes to scoring pipeline, manifests, CBM, LLM driver, or engine patterns.

---

## Data Model

### `data/bot_registrations/{bot_id}.json`

```json
{
  "bot_id": "st-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "bot_name": "TravelBot",
  "client_id": "cs-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "client_secret": "...",
  "webhook_url": "https://platform.kore.ai/hooks/...",
  "platform_url": "https://platform.kore.ai/",
  "registered_by": "candidate@email.com",
  "registered_at": "2026-03-21T10:00:00+00:00",
  "credential_verified_at": "2026-03-21T10:00:00+00:00",
  "credential_status": "verified"
}
```

**Key:** `bot_id` — one record per bot, reused across all submissions for that bot.
**`credential_status`:** `"verified"` | `"failed"` | `"unverified"` (legacy records without verification).

### Submission stub change

The scored result stub (`data/results/scorecard_{session_id}.json`) gains one field:

```json
"bot_id": "st-xxx"
```

This links the submission back to its bot registration record so credentials can be looked up at restart time.

---

## New Routes

### Candidate Portal

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/candidate/register` | Bot registration form |
| `POST` | `/candidate/register` | Validate + save registration, redirect to submit |
| `POST` | `/candidate/register/{bot_id}/update` | Update `platform_url` or `webhook_url` on existing registration |

**`POST /candidate/register/{bot_id}/update` contract:**
- Accepted form fields: `platform_url` (optional), `webhook_url` (optional). `bot_id`, `client_id`, `client_secret`, and `bot_name` are read-only after initial registration.
- On success: redirect to `/candidate/?bot_id={bot_id}`.
- On error (e.g. record not found): return the registration form with inline error message.

### Admin Portal

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/bots` | Bot registry — all registered bots, credential status, submission count |
| `POST` | `/admin/bots/{bot_id}/update` | Edit `platform_url`, `webhook_url`, or re-verify credentials |

**`POST /evaluation/{session_id}/restart` — updated parameter contract:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `mode` | `str` | required | Existing field; `"fresh"` or `"resume"` |
| `kore_platform_url` | `str` | `""` | Optional override; empty = use registration record |
| `kore_client_id` | `str` | `""` | Optional override; empty = use registration record |
| `kore_client_secret` | `str` | `""` | Optional override; empty = use registration record |
| `kore_bot_name` | `str` | `""` | Optional override; empty = use registration record |

Note: `reverify` is not applicable to the restart endpoint. The restart endpoint always runs a jwtgrant pre-flight check unconditionally before dispatching.

**`POST /admin/bots/{bot_id}/update` contract:**
- Accepted form fields: `platform_url` (optional), `webhook_url` (optional), `reverify` (bool flag, optional).
- `bot_id`, `client_id`, `client_secret`, and `bot_name` are read-only after initial registration.
- When `reverify=true`: runs `get_kore_bearer_token(creds, max_retries=0)`, updates `credential_status` and `credential_verified_at`.
- On success: redirect to `/admin/bots`.
- On credential failure during re-verify: redirect to `/admin/bots` with a query param `?error={message}` rendered as a flash message.

---

## Candidate Flow

```
/candidate/register  →  credential pre-flight  →  save bot_registrations/{bot_id}.json
        ↓ (redirect on success)
/candidate/?bot_id={bot_id}  →  bot card shown, no credential fields
        ↓
Evaluation launches with credentials from bot_registrations/{bot_id}.json
```

**Re-submitters:** Skip registration entirely. Navigate to `/candidate/`, enter `bot_id` to look up existing registration, proceed.

**`GET /candidate/` route change:** The existing route (`@router.get("/")` in `candidate/routes.py`) gains an optional `bot_id` query param (`GET /candidate/?bot_id={value}`). When present, the route loads the matching bot registration and pre-populates the Bot Card. When absent, the form shows the Bot ID lookup field instead.

**Bot ID lookup:** Candidates who arrive at `/candidate/` without `?bot_id=` see a lookup input. Submitting it navigates the browser to `GET /candidate/?bot_id={entered_value}` — a standard form GET. If no registration is found, the route returns the page with an inline error: *"Bot not registered — please register your bot first."* No separate API endpoint is needed; the same GET handler covers both the initial load and the lookup result.

**`POST /candidate/submit` form change:** The existing POST handler removes the inline credential fields (`bot_id`, `bot_name`, `client_id`, `client_secret`, `webhook_url`, `platform_url`) and replaces them with a single hidden `bot_id` field. The handler loads credentials from `data/bot_registrations/{bot_id}.json` and raises a form error if the record is missing.

The existing `webhook_url` Form parameter is removed. The handler injects `manifest_data["webhook_url"] = reg.webhook_url` from the bot registration record (replacing the previous `if webhook_url: manifest_data["webhook_url"] = webhook_url` pattern). The registration record's `webhook_url` is always injected — it is mandatory at registration time so it is always present.

**Registration form fields (all mandatory):**
- Bot ID (`st-xxx`)
- Bot Display Name (exact name in Kore.ai XO Platform)
- Client ID
- Client Secret
- Webhook URL
- Platform URL (pre-filled: `https://platform.kore.ai/`, editable)

---

## Pre-Flight Credential Validation

At `POST /candidate/register`, after building `KoreCredentials`:

1. Call `get_kore_bearer_token(creds, max_retries=0)` (jwtgrant exchange, **no retries** — bad credentials must fail fast; the default retry loop would add ~35s latency on registration errors).
2. On failure, return form with specific error message:
   - HTTP 401 → *"Client ID or Secret is incorrect. Check your app credentials in Kore.ai XO Platform."*
   - HTTP 400 with body containing `"errors"` or `"botInfo"` → *"Bot Display Name does not match your bot in Kore.ai XO Platform. Use the exact name shown in your bot settings."* (Kore.ai returns `{"errors": [{"msg": "invalid botInfo", ...}]}` for botInfo mismatches.)
   - Network / ConnectError → *"Could not reach Kore.ai — check your Platform URL or network connection."*
   - Other → *"Credential verification failed: {detail}"*
3. On success → write `bot_registrations/{bot_id}.json` with `credential_status: "verified"`, redirect to `/candidate/?bot_id={bot_id}`.

---

## Submission Form Changes

The existing `candidate_submit.html` (rendered by `GET /candidate/`) removes the inline credential block (bot_id, bot_name, client_id, client_secret, webhook_url, platform_url). Replaced with:

- A **Bot Card** — shows bot name, bot_id, credential status badge, webhook URL (rendered when `bot_id` query param is present and resolves to a known registration).
- A hidden `bot_id` field inside the submission form (pre-filled from `?bot_id=` query param).
- A **"Register a different bot →"** link pointing to `/candidate/register`.
- A **Bot ID lookup form** (shown when no `?bot_id=` param): a text input and a submit button that issues `GET /candidate/?bot_id={value}`.

If the `?bot_id=` resolves to no registration, the GET handler returns the page with an inline error and the lookup form: *"Bot not registered — please register your bot first."*

---

## Admin Restart — Inline Credential Form

When admin clicks Restart on a submission row, the row expands inline to show:

```
[Mode: Fresh ▾]  [Platform URL: https://platform.kore.ai/]
[Client ID: cs-xxx (pre-filled)]  [Client Secret: ••••••• (pre-filled)]
[Bot Name: TravelBot (pre-filled)]
[Confirm Restart]
```

- Fields are **pre-filled from `bot_registrations/{bot_id}.json`** if `bot_id` is on the stub.
- For legacy stubs (no `bot_id`), fields are empty — admin pastes manually.
- Submitting runs a lightweight jwtgrant check (`max_retries=0`) before dispatching the background task. On credential failure, the endpoint returns `JSONResponse({"error": "<message>"}, status_code=400)` — matching the existing error response pattern. The admin JS displays this inline without a page reload. The same error messages as Pre-Flight Credential Validation apply (401 → "Client ID or Secret is incorrect", etc.). On success, the existing redirect behaviour is unchanged.

**Restart endpoint — updated `Form(...)` parameters:** The existing `POST /evaluation/{session_id}/restart` gains four optional form fields: `kore_platform_url`, `kore_client_id`, `kore_client_secret`, `kore_bot_name`. The existing `mode` field is unchanged.

**Empty field fallback:** When the form fields are submitted empty (i.e. admin does not override), the handler reads `original_stub.get("bot_id")`. Only when this value is a non-empty string does the handler attempt to load `data/bot_registrations/{bot_id}.json`. If `bot_id` is absent or empty in the stub (legacy submissions), or if the registration file does not exist, the handler falls back to `kore_creds=None` — preserving existing behaviour.

---

## Engine + Driver Fixes

### `driver.py` — Explicit `session: {"new": false}`

Current behaviour in `send_message`:
- First message: sends `{"session": {"new": True}}`.
- Subsequent messages when `_kore_session_id` is set from a prior response: sends `{"session": {"id": kore_session_id}}`.
- Subsequent messages when no session ID has been received yet: omits the session field entirely.

**Change:** Replace the `elif self._kore_session_id` branch. After the first message, all subsequent calls send `{"session": {"new": False}}` regardless of whether a session ID was received. Session continuity in Kore.ai webhook v2 is maintained by `from.id` — the `session.id` field is informational only and is not required for continuity. Sending `{"new": False}` is cleaner and matches Kore.ai webhook v2 docs explicitly.

```python
if self._is_new_session:
    payload["session"] = {"new": True}
else:
    payload["session"] = {"new": False}
```

`_kore_session_id` is still read from the first response and stored (for the post-eval getSessions lookup), but it is no longer sent back in subsequent message payloads.

### Post-Eval `getSessions` Lookup

After `run_full_evaluation` completes, call via `KoreAPIClient.get_sessions_by_user`:

```
GET {platform_url}/api/public/bot/{bot_id}/getSessions
    ?userId={from_id}&channel=webhook&limit=1
    Authorization: bearer {admin_jwt}
```

Expected response (Kore.ai public API):
```json
{"sessions": [{"sessionId": "...", ...}], "total": 1}
```

Extract `sessions[0]["sessionId"]` and store in the scorecard as `kore_session_id`. This gives admin one-click access to debug logs for the exact conversation driven during evaluation.

**Error handling:** If `get_sessions_by_user` raises any exception (network error, 404, empty sessions list), log a warning and set `kore_session_id = None` in the scorecard. This call is non-blocking — scorecard is always written regardless of whether the session ID is retrieved.

**Caller in `engine.py`:** Pass `webhook_client._from_id` as the `from_id` argument. `_from_id` is the `eval-req-post-{submission_id}` string used in all webhook messages — the same identifier Kore.ai logs against the session.

**Token scope:** `get_sessions_by_user` uses `_api_get` (standard `Authorization: bearer` header), not `_api_get_kore`. The Kore.ai public getSessions API is on the standard public API tier.

**`get_sessions_by_user` method signature:**
```python
async def get_sessions_by_user(self, from_id: str) -> str | None:
    """Return the most recent sessionId for from_id, or None on any failure."""
```
(`async def` to match `KoreAPIClient`'s async HTTP design.)

### `KoreAPIClient` Construction

`EvaluationEngine` constructs `KoreAPIClient` from `KoreCredentials` loaded from the bot registration record (not from the submission-time bearer token). The bearer token is still obtained at evaluation start via `get_kore_bearer_token`, but credentials come from the persisted record.

### `BotRegistration` → `KoreCredentials` mapping

`registration.py` exports a helper:

```python
def to_kore_credentials(reg: BotRegistration) -> KoreCredentials:
    """Convert a BotRegistration to KoreCredentials for engine/driver use."""
```

This is the sole conversion point. Call sites in `candidate/routes.py` and `admin/routes.py` use this helper rather than constructing `KoreCredentials` ad hoc.

`KoreCredentials.validate()` in `jwt_auth.py` is updated to enforce that `bot_name` is non-empty. The validation message is: *"bot_name is required for Kore.ai jwtgrant authentication."*

`to_kore_credentials` calls `validate()` after constructing the credentials object. If the returned list is non-empty, it raises `ValueError` with the joined error messages. This gives a fail-fast guarantee before any jwtgrant call is attempted.

---

## Admin Bot Registry Page (`/admin/bots`)

Table columns:
- Bot Name
- Bot ID
- Registered By
- Credential Status (verified / failed / unverified)
- Last Verified
- Submission Count (link to filtered submissions)
- Actions: Re-verify, Edit Platform URL, Edit Webhook URL

---

## Migration / Backwards Compatibility

- Old submission stubs without `bot_id` continue to work. Admin restart shows empty credential form (existing behaviour from Task 15).
- No database migration needed — new directory `data/bot_registrations/` is created on first registration.

---

## Security Notes

- Credentials stored as plain text in `data/bot_registrations/`. Acceptable: internal on-prem evaluation platform, candidates already trust the evaluator.
- `client_secret` is never logged, never included in API responses, never rendered in templates except as a password field. The admin restart form pre-fills `client_secret` in `<input type="password" autocomplete="off">`. This is acceptable for an internal on-prem admin panel — the value is sent as a form POST field and is not exposed beyond the admin session.
- `data/bot_registrations/` must be excluded from git. The top-level `data/` directory is already in `.gitignore`, so no additional `.gitignore` change is needed — this is noted here for clarity only.

---

## Files Affected

### New files
| File | Responsibility |
|------|---------------|
| `src/governiq/candidate/registration.py` | `BotRegistration` dataclass (not Pydantic — matches `KoreCredentials` pattern), `load_bot_registration`, `save_bot_registration`, `to_kore_credentials` |
| `src/governiq/templates/candidate_register.html` | Bot registration form |
| `src/governiq/templates/admin_bots.html` | Admin bot registry table; must render inline flash error when `?error=` query param is present (read via `request.query_params.get('error')`) |
| `tests/test_bot_registration.py` | Unit + integration tests for registration flow |

### Modified files
| File | What changes |
|------|-------------|
| `src/governiq/candidate/routes.py` | Add register routes, remove inline credentials from submit handler, load from registration; add `bot_id` field to the stub dict written at submission time |
| `src/governiq/templates/candidate_submit.html` | Replace credential block with Bot Card + bot_id lookup |
| `src/governiq/admin/routes.py` | Add `/admin/bots` route, update restart endpoint to pre-fill from registration |
| `src/governiq/templates/admin_dashboard.html` | Inline credential expand on restart row; convert restart form submission to `fetch()` call — `status 400` + `Content-Type: application/json` → display `response.error` inline; `status 303` redirect → `window.location.href` from response or follow redirect |
| `src/governiq/webhook/driver.py` | `session: {"new": false}` fix; update `KoreWebhookClient` class docstring and `send_message` method docstring to remove obsolete "Subsequent: session.id = pinned koreSessionId" language |
| `src/governiq/core/engine.py` | Post-eval getSessions lookup, KoreAPIClient from registration |
| `src/governiq/webhook/kore_api.py` | Add `get_sessions_by_user` method |
| `src/governiq/webhook/jwt_auth.py` | Update `KoreCredentials.validate()` to enforce `bot_name` non-empty; update `platform_url` default from `"https://bots.kore.ai"` to `"https://platform.kore.ai/"` to match the registration form pre-fill |

---

## Restart + Review Bug Fixes

### Problem

The admin restart endpoint writes the new stub to disk **before** doing the manifest lookup. When the lookup fails (e.g. because `manifest_id` is absent on an old or restart-chain stub), the handler returns an error — but the new stub already exists on disk with `status: "running"` and no evaluation ever launched. That zombie stub appears in the dashboard as a permanently-running evaluation with no log.

Additionally, restarting a session that was itself the product of a previous restart can propagate missing fields indefinitely — each restart spreads `{**original_stub}`, so any field absent in generation N is absent in generation N+1.

The review endpoint crashes with a 500 when a stub has only minimal fields (e.g. just `session_id`, `status`, `log_file`), because the template or Scorecard construction expects fields like `assessment_name`, `task_scores`, and `candidate_id`.

### Fixes

**Restart handler — both `mode=fresh` and `mode=resume`:**

1. **Manifest lookup happens first** — before any new stub is written.
   - Extract `manifest_id = original_stub.get("manifest_id", "").strip()`.
   - If empty, attempt fallback: `assessment_name = original_stub.get("assessment_name", "").strip()`. Only attempt this search if `assessment_name` is non-empty — an empty string must not be matched against manifest files (risk of false-positive on any manifest with a missing or empty `assessment_name`). If `assessment_name` is also empty, skip the search entirely and go directly to the 422 response.
   - If still not found, return `JSONResponse({"error": "..."}, status_code=422)` **without** creating any new stub file.
2. **New stub written after successful manifest lookup**, with `manifest_id` and `assessment_name` injected **explicitly** from the found `manifest_obj` (not just via spread). Spread is still used for other fields, but manifest identity fields are always overwritten from the live manifest object.
3. **No orphaned stubs on the synchronous path** — if any error occurs in the synchronous path after stub creation but before `background_tasks.add_task()`, the new stub is deleted before returning the error response. This covers unexpected exceptions between stub write and task dispatch. It does **not** cover failures inside the background task itself (`_run_evaluation_background` / `_do_resume`) — those failures happen after `add_task()` has already been called and there is no response to return. Background task failures set `status: "error"` on the stub via the existing error-handling path in `_run_evaluation_background` (this is existing behaviour; the spec does not change it).

**Review endpoint (`GET /admin/review/{session_id}`):**

The route handler must unpack all stub fields into explicitly safe-defaulted local variables before building the template context — it must not pass the raw stub dict to the template and rely on Jinja2 attribute access. Jinja2 raises `UndefinedError` on missing keys depending on the `undefined` setting; accessing `.get()` is not available in templates for dicts passed via `{{ sc.field }}` syntax.

The handler builds an explicit context dict with safe defaults, e.g.:
```python
context = {
    "session_id": stub.get("session_id", ""),
    "candidate_id": stub.get("candidate_id", "N/A"),
    "assessment_name": stub.get("assessment_name", "N/A"),
    "overall_score": stub.get("overall_score", None),
    "task_scores": stub.get("task_scores", []),
    "compliance_results": stub.get("compliance_results", []),
    ...
}
```
`admin_review.html` is updated to use these context variables (not dict attribute access). The page renders "Not available" for missing data instead of raising a 500.

---

## Eval Observability — Live Conversation Log

### Problem

When an evaluation is running, the admin has no visibility into what is happening. When it fails or halts, the only debug signal is `halt_reason` in the stub — a single string with no surrounding context. There is no way to see what the bot said, what the LLM decided, or at which step things went wrong.

### Goals

- Admin can open a per-evaluation conversation page and watch the webhook exchange in real time as it happens.
- The same page shows the full log for completed or failed evaluations (persistent — the JSONL file is already written per session).
- All event types are shown: user messages sent to the bot, bot responses received, LLM intent classifications, entity injections, task boundaries, errors, and halt events.
- Multiple evaluations can be watched simultaneously by opening multiple browser tabs.
- No new Python packages required.
- Auth note: the admin portal currently has no session/cookie auth guard. The `/stream`, `/log`, and `/conversation` endpoints are under `/admin/` and are admin-only by convention only — formal auth is deferred. All three endpoints must validate that `session_id` is a well-formed UUID (same pattern as the restart endpoint: `re.fullmatch(r'[0-9a-f]{8}-...')`) to prevent path traversal. Streaming eval content to unauthenticated callers is an accepted risk for this on-prem internal platform.

### Data Model — Structured Eval Events (additions to existing JSONL log)

Each line in `data/logs/eval_{session_id}.jsonl` is a JSON object. New event types added alongside any existing event types:

```json
{"type": "webhook_turn_sent",    "ts": "<ISO>", "task_id": "T1", "step": 2, "content": "I'd like to book a flight"}
{"type": "webhook_turn_received","ts": "<ISO>", "task_id": "T1", "step": 2, "content": "Sure! What's your destination?"}
{"type": "intent_classified",    "ts": "<ISO>", "task_id": "T1", "step": 2, "intent": "entity_request", "method": "llm"|"rule_based"}
{"type": "entity_injected",      "ts": "<ISO>", "task_id": "T1", "step": 2, "entity_key": "destination", "value": "London"}
{"type": "task_started",         "ts": "<ISO>", "task_id": "T1", "task_name": "Book a Flight"}
{"type": "task_completed",       "ts": "<ISO>", "task_id": "T1", "task_name": "Book a Flight", "passed": true}
{"type": "task_failed",          "ts": "<ISO>", "task_id": "T1", "task_name": "Book a Flight", "reason": "..."}
{"type": "llm_call",             "ts": "<ISO>", "task_id": "T1", "purpose": "classification"|"generation", "result": "..."}
{"type": "engine_error",         "ts": "<ISO>", "task_id": "T1", "error": "...", "halt_reason": "..."}
{"type": "eval_started",         "ts": "<ISO>", "session_id": "..."}
{"type": "eval_completed",       "ts": "<ISO>", "session_id": "...", "final_score": 82.5}
```

**Schema compatibility:** The existing `EvalLogger.log()` method writes entries with the schema `{"ts", "task_id", "level", "event", "detail", "raw"}`. The new structured event types use a different top-level key (`type` instead of `event`). New methods write directly to the JSONL file (bypassing the existing `log()` method) so as not to pollute old-schema entries with new fields. Historical JSONL files therefore contain a **mixed schema** — old entries have `event`, new entries have `type`. The conversation page JavaScript must handle both: render old-schema lines as plain log entries (show `detail` field as a gray system chip), and new-schema lines as typed events (render per the table below). The discriminator is presence of `"type"` key.

For the `llm_call` event: only the `result` field (the LLM text output) is logged — not the system prompt or user prompt. This is intentional: prompts contain bot response text which could be lengthy and is already visible as `webhook_turn_received` events.

`eval_started` is emitted by `engine.py` at the top of `run_full_evaluation`, before the first task begins. `EvalLogger` gets one new method per event type (e.g. `log_webhook_turn_sent(task_id, step, content)`). Engine and driver call these at each conversation step.

### New Route — SSE Stream

```
GET /admin/evaluation/{session_id}/stream
```

- Returns `Content-Type: text/event-stream` (SSE).
- Opens `data/logs/eval_{session_id}.jsonl`. Emits each existing line immediately as `data: <json>\n\n`.
- Polls for new lines every 500 ms while the stub's `status` field is `"running"`.
- When status transitions to anything other than `"running"`, emits a final `event: done\ndata: {}\n\n` and closes.
- If the log file does not exist yet (eval just started), polls at 500 ms intervals for up to 10 s. As soon as the file appears during the wait, immediately stop waiting and enter the main tail loop — do not wait the full 10 s. If the file never appears within 10 s, emit only the `done` event and close.
- No new packages: uses FastAPI's `StreamingResponse` with an async generator and `asyncio.sleep(0.5)` for the tail loop.
- Admin-only: protected by the same session/auth guard as all `/admin/` routes.

### New Route — Conversation Page

```
GET /admin/evaluation/{session_id}/conversation
```

- Renders `admin_conversation.html` — a new Jinja2 template.
- Template receives: `session_id`, `candidate_id`, `assessment_name`, `status`, `halt_reason` (all from the stub; safe defaults if missing).
- JavaScript opens `EventSource("/admin/evaluation/{session_id}/stream")` on page load.
- Renders events as a chat-style timeline:

| Event type | Rendering |
|-----------|-----------|
| `webhook_turn_sent` | Right-aligned bubble (blue) — "Simulated User" |
| `webhook_turn_received` | Left-aligned bubble (gray) — "Bot" |
| `intent_classified` | Center chip — `intent: entity_request (llm)` |
| `entity_injected` | Center chip — `→ destination = "London"` |
| `task_started` | Section header divider — `── Task 1: Book a Flight ──` |
| `task_completed` | Green banner — `✓ Task 1 passed` |
| `task_failed` | Amber banner — `✗ Task 1 failed: <reason>` |
| `llm_call` | Collapsed detail row — expandable on click |
| `engine_error` | Red banner — `⚠ Halted: <halt_reason>` |
| `eval_completed` | Final green banner with score |

- When `event: done` received: stop EventSource, show "Evaluation complete" banner if not already shown from `eval_completed` event.
- When status is not `"running"` on page load: JS skips EventSource and renders all log lines from a single `GET /admin/evaluation/{session_id}/log` JSON endpoint (returns array of all JSONL lines). This avoids SSE overhead for historical views.
- Auto-scrolls to bottom while live; stops auto-scroll when user manually scrolls up.

### New Route — Log JSON (for completed evals)

```
GET /admin/evaluation/{session_id}/log
```

- Returns `{"events": [...]}` — all lines from the JSONL file as a JSON array.
- Used by the conversation page JavaScript for historical (non-running) evals.
- Returns `{"events": []}` if the log file does not exist.

### Admin Dashboard Changes

**Per-row additions to `admin_dashboard.html`:**

- **"Watch Live" button** — shown only when the enriched `display_status == "running"` (not raw `status`) — this excludes stale/zombie stubs that show `status: "running"` in the raw stub but are detected as stale by `_enrich_submission`. Opens `/admin/evaluation/{session_id}/conversation` in a new tab (`target="_blank"`).
- **"View Log" button** — shown for all evals. Opens the same conversation page (shows historical log for completed evals, live stream for running ones).
- **Inline error/halt surface** — below the status badge, show `halt_reason` or `error` if present and non-null. Truncated to 80 chars with a tooltip for the full text. This gives the admin instant debug context without opening the conversation page.

---

## Updated Files Affected (additions for observability + bug fixes)

### New files (additions)
| File | Responsibility |
|------|---------------|
| `src/governiq/templates/admin_conversation.html` | Per-evaluation conversation/log page with live SSE rendering |

### Modified files (additions)
| File | What changes |
|------|-------------|
| `src/governiq/core/eval_logger.py` | Add `log_webhook_turn_sent`, `log_webhook_turn_received`, `log_intent_classified`, `log_entity_injected`, `log_task_started`, `log_task_completed`, `log_task_failed`, `log_llm_call`, `log_engine_error`, `log_eval_started`, `log_eval_completed` methods |
| `src/governiq/core/engine.py` | Call new EvalLogger methods at each conversation step and task boundary |
| `src/governiq/webhook/driver.py` | Pass `task_id` and `step` context through to logging call sites |
| `src/governiq/admin/routes.py` | Fix restart handler (manifest-first ordering, no orphan stubs); fix review endpoint (explicit safe-defaulted context dict); add `/admin/evaluation/{id}/stream`, `/admin/evaluation/{id}/conversation`, `/admin/evaluation/{id}/log` routes (all with UUID validation on session_id) |
| `src/governiq/templates/admin_review.html` | Replace direct stub attribute access with context variables supplied by the updated route handler; render "Not available" for missing fields |
| `src/governiq/templates/admin_dashboard.html` | Add "Watch Live" + "View Log" buttons per row; inline `halt_reason`/`error` surface |
| `tests/test_bot_registration.py` | Add tests for bug fixes: restart with missing manifest_id (fallback to assessment_name), no orphan stub on manifest lookup failure, review endpoint defensive rendering |
