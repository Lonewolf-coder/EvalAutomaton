# GovernIQ Production Readiness — Design Spec

**Date:** 2026-03-19
**Status:** Approved
**Scope:** Functional completeness, non-technical UX, multi-provider AI config, system health monitoring

---

## Goal

Make GovernIQ fully functional and testable for non-technical users (admins, evaluators, candidates) across multiple machines. No terminal interaction required after initial server start. Any admin can configure the system, switch AI providers, and understand system status without technical knowledge.

---

## Target Users

| Role | Portal | Technical level |
|---|---|---|
| Candidate | `/candidate/` | None — follows instructions |
| Evaluator / Admin | `/admin/` | None — uses UI only |
| IT / Setup person | Terminal (once only) | Starts the server, nothing else |

---

## Architecture

### No backend changes to core evaluation engine
All 12 patterns, scoring, CBM parser, RuntimeContext, and manifest system remain unchanged. This spec touches: routes, templates, a new health endpoint, settings persistence, and plagiarism wiring.

### Endpoint strategy: `/health` vs `/api/v1/health`
`main.py` already registers a simple `GET /health` that returns `{"status": "ok"}`. This endpoint is retained as a process liveness check (used by load balancers / ops tooling). The new `GET /api/v1/health` endpoint is separate — it performs live subsystem checks (AI model reachability, storage writability, manifest presence) and returns structured JSON consumed by the health bar. The two endpoints coexist and serve different purposes.

### Config persistence: `data/llm_config.json`
LLM provider selection and API keys stored locally per machine. Written by the Settings page POST handler. Never committed to git. Loaded at startup and on every health check.

### Data directory auto-init
`main.py` startup (via FastAPI lifespan context manager) creates `data/`, `data/results/`, `data/runtime_contexts/` if they don't exist. App never crashes on first run.

### Async submission pipeline (Component 6a)
The candidate submit handler is synchronous today. To support a progress indicator without blocking, the POST handler must:
1. Create a results file with `{"status": "running", "session_id": "..."}` immediately
2. Return the `session_id` to the frontend
3. Launch evaluation via FastAPI `BackgroundTasks`
4. Frontend polls `GET /api/v1/results/{session_id}` every 3 seconds until `status != "running"`
5. Background task writes final scorecard to the results file on completion
This is implemented inside `candidate/routes.py` — no new files needed.

---

## Component 1 — Persistent System Health Bar

### Location
Rendered in `base.html` immediately below the top nav. Present on **every page** in both portals.

### States

| State | Condition | Bar colour | Dot animation |
|---|---|---|---|
| Error | Any subsystem is `failing` | Red (`rgba(220,38,38,0.1)`) | Pulse red, 2s |
| Warning | All passing, advisory exists | Amber (`rgba(245,158,11,0.08)`) | Pulse amber, 2.5s |
| OK | All subsystems healthy | Green (`rgba(52,211,153,0.06)`) | Pulse green, 3s |

### Bar content (collapsed)
- Pulsing dot
- Lucide lead icon: `alert-circle` (error) / `alert-triangle` (warning) / `check-circle-2` (ok)
- Plain-English summary message
- Subsystem chips: AI Model, Storage, Manifests, App — each with `check-circle` or `x-circle` Lucide icon
- `chevron-down` caret

### Expanded panel (click to toggle)
Grid of 4 subsystem cards. Each card:
- Top accent line (red/amber/green)
- Subsystem name (small caps label)
- Status line with Lucide icon + text
- Plain-English description (no technical jargon, no error codes)
- Action button: "How to fix" link or "No action needed"

### Subsystems monitored

| Subsystem | Check | Failure message | Fix action |
|---|---|---|---|
| AI Model | HTTP GET to configured provider URL | "LM Studio is not running. Start LM Studio and load a model." | Link to `/admin/settings` |
| Storage | `data/results/` directory writable | "Results cannot be saved. Check disk space." | Link to docs |
| Manifests | At least 1 active manifest in `manifests/` | "No assessment is configured. Load a manifest." | Link to `/admin/manifests` |
| App | Always passes if page renders | "GovernIQ is running correctly." | None |

### Plain-English message rules
- No HTTP status codes in user-facing text
- No IP addresses or port numbers in error messages
- No Python exception names
- Always says what happened AND what to do

### API endpoint: `GET /api/v1/health`
This is a **new** endpoint added to `src/governiq/api/routes.py`. It does not replace the existing `GET /health` in `main.py`.

```
GET /api/v1/health
Response: {
  "status": "error" | "warning" | "ok",
  "subsystems": {
    "ai_model":  { "status": "ok"|"warning"|"failing", "message": "...", "detail": "..." },
    "storage":   { "status": "ok"|"warning"|"failing", "message": "...", "detail": "..." },
    "manifests": { "status": "ok"|"warning"|"failing", "message": "...", "detail": "..." },
    "app":       { "status": "ok",                     "message": "...", "detail": "..." }
  },
  "advisories": ["..."]
}
```

### API endpoint: `POST /api/v1/health/test-ai`
This is a **new** endpoint added to `src/governiq/api/routes.py`. Accepts a provider config payload and tests the connection without saving it. Returns the same subsystem schema as above for `ai_model` only.

```
POST /api/v1/health/test-ai
Body: { "provider": "lmstudio"|"anthropic"|"openai"|"azure"|"ollama"|"gemini", "url": "...", "api_key": "..." }
Response: { "status": "ok"|"failing", "message": "..." }
```

---

## Component 2 — Critical Fixes

### 2a — Data directory auto-init
**File:** `src/governiq/main.py`

Use FastAPI's lifespan context manager pattern. `main.py` has no existing `@app.on_event("startup")` decorator — none needs to be removed. The existing `FastAPI(...)` constructor takes `title`, `description`, and `version` only; add `lifespan=lifespan` to it.

The server **must be started from the project root directory** (the directory containing `src/`) because the rest of the codebase uses relative paths like `./data/`. The lifespan code uses the same convention:

```python
from contextlib import asynccontextmanager
from pathlib import Path

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure data directories exist (relative to CWD = project root)
    for d in ["data", "data/results", "data/runtime_contexts", "data/manifests", "data/fingerprints"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    yield
    # Shutdown: nothing needed

app = FastAPI(title=..., description=..., version=..., lifespan=lifespan)
```

Add to `.env.example` and startup docs: "Run uvicorn from the project root directory."

### 2b — Remove dead scoring code
**File:** `src/governiq/core/scoring.py`

**Authorisation note:** CLAUDE.md states dead code "should be flagged but not deleted without explicit instruction." This spec is that explicit instruction. The `compute_weighted_score()` method uses hardcoded 40/40 weights that contradict the correct 80/10/10 formula and would mislead any implementer who runs it.

Delete `compute_weighted_score()` method entirely (lines ~193–213). Add comment above `overall_score` property:
```python
# Scoring formula: Webhook 80% + FAQ 10% + Compliance 10%
# CBM structural audit is informational only — 0% weight
```

### 2c — Fix how_it_works.html scoring display
**File:** `src/governiq/templates/how_it_works.html`
Update scoring diagram to show correct weights:
- Webhook Functional Testing — 80%
- FAQ Semantic Similarity — 10%
- Compliance Checks — 10%
- CBM Structural Audit — Informational only (0%)

### 2d — Fix datetime deprecation warnings
**Files:** `src/governiq/core/engine.py`, `src/governiq/core/runtime_context.py`
Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`.
Add `from datetime import timezone` where missing.

### 2e — Create .env.example
**File:** `.env.example` (new file, project root)
Document all environment variables in plain English:
```
# AI Provider Keys (only needed if NOT using LM Studio)
ANTHROPIC_API_KEY=   # Get from console.anthropic.com
OPENAI_API_KEY=      # Get from platform.openai.com

# Kore.ai credentials (optional — candidates can also enter these in the submission form)
KORE_CLIENT_ID=
KORE_CLIENT_SECRET=

# App settings
PORT=8000            # Port to run GovernIQ on (default: 8000)
```

---

## Component 3 — Multi-Provider AI Settings Page

### Location
`/admin/settings` — **new** GET + POST route added to `src/governiq/admin/routes.py`. The existing `/admin/llm-config` route (if present) is kept for backward compatibility but redirects to `/admin/settings`.

### Template: `admin_settings.html` (new file)
Non-technical redesign of the LLM config page.

### Provider selection
Six provider cards displayed in a 2×3 grid. Each card shows:
- Provider name and logo/icon
- One-line description ("Free, runs on your PC" / "Best evaluation quality" etc.)
- What's required (URL field / API key field)
- Selected state highlighted with violet border

**Providers:**

| Card | Icon | Description | Fields |
|---|---|---|---|
| LM Studio | `cpu` | Free · runs on your PC · no internet needed | Address (default: `http://localhost:1234`) |
| Claude (Anthropic) | `bot` | Best evaluation quality · requires API key | API Key (masked) |
| OpenAI | `zap` | Great evaluation quality · requires API key | API Key (masked) |
| Azure OpenAI | `cloud` | For corporate environments | Endpoint + API Key |
| Ollama | `terminal` | Free · technical users | Address |
| Google Gemini | `sparkles` | Alternative cloud option | API Key (masked) |

### Interaction flow
1. User clicks a provider card → form fields slide open below
2. User fills in required fields
3. "Test Connection" button → calls `POST /api/v1/health/test-ai` with the new config
4. Success: green banner "Connected — [Provider] is working correctly"
5. Failure: red banner with plain-English message and specific fix instructions
6. "Save" button persists to `data/llm_config.json`
7. Health bar updates on next page load

### API key security
- Masked input fields (type="password") with show/hide toggle (Lucide `eye`/`eye-off`)
- Keys stored in `data/llm_config.json` (local only, not in git)
- Keys never appear in logs
- On page load, show "••••••••" placeholder if key already saved

### Portability
- Config is per-machine — intentional
- Health bar turns red on unconfigured machines: "AI model not configured"
- Click → expanded panel → "Configure AI" action → `/admin/settings`
- Takes ~30 seconds to reconfigure on a new machine

---

## Component 4 — Plagiarism Detection Integration

### Current state
`PlagiarismDetector` and `FingerprintEngine` fully implemented in `src/governiq/plagiarism/`. Not called anywhere in submission flow.

### Scorecard schema change (required)
**File:** `src/governiq/core/scoring.py` — `Scorecard` dataclass

Add two fields to the `Scorecard` dataclass in the `# Flags` section:
```python
plagiarism_flag: bool = False
plagiarism_message: str = ""
```

Also add both fields to the `to_dict()` method in `Scorecard` so they are serialised to JSON (alongside the existing flag fields).

`PlagiarismReport.message` (a `str`) is the field to copy into `scorecard.plagiarism_message`. `PlagiarismReport` does not have a `.detail` attribute — do not use `.detail`.

### Integration point
`src/governiq/candidate/routes.py` — POST `/candidate/submit` handler, after CBM parse, before webhook evaluation.

### Behaviour
Import: `from governiq.plagiarism.detector import detect, PlagiarismRisk`

Call: `result = detect(export_data, manifest.assessment_type, session_id)`

- `export_data` is the parsed `appDefinition.json` dict from the bot ZIP
- `assessment_type` comes from the loaded manifest (e.g., `"travel"`)
- `session_id` is the newly created session identifier

If `result.risk_level != PlagiarismRisk.NONE`: set `scorecard.plagiarism_flag = True`, `scorecard.plagiarism_message = result.message`

- `result.message` is a human-readable string containing the risk level and matching submission IDs (e.g., `"HIGH — Bot structure identical to: sub_abc, sub_def"`). It is intended for **admin display only** — it contains internal session IDs.
- Evaluation **still runs and scores** — plagiarism flag is advisory, not a blocker
- Admin decides action

### UI changes

**`candidate_report.html`:** If `scorecard.plagiarism_flag`:
- Amber warning banner below page header using the **hardcoded generic string** (do NOT render `scorecard.plagiarism_message` — it contains internal session IDs): "This submission has been flagged for similarity to a previous submission. Your evaluator has been notified."
- Uses existing `.alert.alert-warning` CSS class from `base.html`

**`admin_review.html`:** If `scorecard.plagiarism_flag`:
- Red warning banner rendering the admin-safe detail: "Flagged: Possible duplicate submission — {{ scorecard.plagiarism_message }}"
- Uses existing `.alert.alert-danger` CSS class from `base.html`

**`admin_dashboard.html`:** Submissions table row:
- Add `badge-warn` "Flagged" badge in the status column when `plagiarism_flag = True`
- The `.alert.alert-warning` and `.alert.alert-danger` classes are already defined in `base.html` — no new CSS needed.

---

## Component 5 — Admin Compare Diff Logic

### Current state
`/admin/compare` route exists in `src/governiq/admin/routes.py`. It already:
- Groups all submissions by candidate + assessment and detects duplicate submission sets
- Computes `similarity_groups` (with `score_range` min/max per group)
- Reads `left` and `right` query params and loads the two selected scorecards as `left_sc` / `right_sc`
- Passes `similarity_groups`, `left`, `right`, `left_id`, `right_id` to the template

What it does **not** yet do:
- Align tasks between the two scorecards by `task_id`
- Compute per-task score deltas
- Flag tasks where the delta exceeds 20%

The template currently shows raw JSON for the two scorecards. The similarity group sidebar works.

### Implementation
Route already uses `?left={id}&right={id}` — keep these param names throughout. Do not change to `a`/`b`.

Extend the existing route handler (no new files). Do not remove the existing `similarity_groups` logic:
1. Scorecards are already loaded as `left_sc` / `right_sc` — no change needed there
2. Add task alignment: zip tasks from both scorecards by `task_id`
3. For each aligned task: compute score delta, flag if `abs(delta) > 0.20`
4. Add `task_diff` list and `overall_diff` to template context alongside existing variables

### Template changes (`admin_compare.html`)
- Side-by-side score table: Left candidate vs Right candidate per task
- Colour-coded deltas: green (left higher), red (right higher), grey (similar)
- "Significant difference" badge on tasks with >20% gap
- Overall scores compared at top with score rings
- No raw JSON exposed — clean table only

### Dashboard integration
"Compare" button on admin dashboard submissions table — selects two rows and opens `/admin/compare?left=...&right=...`

---

## Component 6 — Non-Technical UX Polish

### 6a — Candidate submission progress indicator
**File:** `candidate_submit.html` + `src/governiq/candidate/routes.py`

The submit POST handler runs evaluation synchronously today. To show a progress indicator:

**Backend change (routes.py):**
1. On POST, validate input and parse CBM synchronously (fast, < 1s)
2. Create a stub results entry immediately: `{"session_id": "...", "status": "running"}`
3. Launch full evaluation as a FastAPI `BackgroundTasks` task
4. Return a JSON response `{"session_id": "..."}` immediately (no redirect)

**Frontend change (candidate_submit.html):**
After form submit:
- Replace submit button area with an inline progress panel showing:
  - Step 1: "Checking your bot file..." (CBM parse — completes synchronously)
  - Step 2: "Testing your bot..." (webhook evaluation, longest step)
  - Step 3: "Calculating your score..." (scoring)
- Poll `GET /api/v1/results/{session_id}` every 3 seconds — this endpoint **already exists** in `src/governiq/api/routes.py` (reads `data/results/scorecard_{session_id}.json`)
- The stub file written by the BackgroundTask must use the same filename convention: `scorecard_{session_id}.json`, so the existing endpoint can serve it immediately during polling
- When the response `status` field is not `"running"`, redirect to the report page

### 6b — Branded error pages
**File:** New `error.html` template
Replace FastAPI default error pages with GovernIQ-branded screens showing:
- Clear heading: "Something went wrong" / "Page not found"
- Plain-English explanation
- "Go to Dashboard" / "Try again" buttons
- No stack traces, no HTTP status codes visible

### 6c — Empty state improvements
All empty states across templates updated with:
- Lucide icon
- Clear heading
- One-sentence explanation
- Specific next-step action button

| Page | Empty state action |
|---|---|
| Admin dashboard | "No submissions yet — candidates submit at [URL]" |
| Candidate history | "No submissions yet — submit your first assessment" button |
| Admin manifests | "No manifests — create your first manifest" button |
| Admin compare | "Select two submissions from the dashboard to compare" |

### 6d — Form validation (candidate submit)
Replace silent failures with inline field errors:
- "Please select an assessment" (no manifest chosen)
- "Please upload a bot export file (.zip or .json)"
- "Please enter your webhook URL to enable live testing"
All in plain English, shown inline below the field.

---

## File Map

| File | Change type | Component |
|---|---|---|
| `src/governiq/main.py` | Modify | 2a (data dir init via lifespan) |
| `src/governiq/core/scoring.py` | Modify | 2b (delete dead code) + 4 (add plagiarism fields to Scorecard) |
| `src/governiq/templates/how_it_works.html` | Modify | 2c (scoring percentages) |
| `src/governiq/core/engine.py` | Modify | 2d (datetime fix) |
| `src/governiq/core/runtime_context.py` | Modify | 2d (datetime fix) |
| `.env.example` | Create | 2e |
| `src/governiq/api/routes.py` | Modify | New `/api/v1/health` + `/api/v1/health/test-ai` endpoints (Component 1, 3) |
| `src/governiq/templates/base.html` | Modify | Health bar HTML + JS polling (Component 1) |
| `src/governiq/admin/routes.py` | Modify | New `/admin/settings` GET+POST route, extend compare route (Components 3, 5) |
| `src/governiq/templates/admin_settings.html` | Create | Multi-provider settings (Component 3) |
| `src/governiq/templates/admin_compare.html` | Modify | Diff logic rendering (Component 5) |
| `src/governiq/candidate/routes.py` | Modify | Plagiarism wiring, BackgroundTasks, progress polling (Components 4, 6a) |
| `src/governiq/templates/candidate_submit.html` | Modify | Progress indicator, form validation (Component 6a, 6d) |
| `src/governiq/templates/candidate_report.html` | Modify | Plagiarism banner (Component 4) |
| `src/governiq/templates/admin_review.html` | Modify | Plagiarism banner (Component 4) |
| `src/governiq/templates/admin_dashboard.html` | Modify | Plagiarism badge, compare button (Components 4, 5) |
| `src/governiq/templates/error.html` | Create | Branded error pages (Component 6b) |
| `tests/test_health.py` | Create | Health endpoint tests |
| `tests/test_plagiarism_integration.py` | Create | Plagiarism wiring tests |
| `tests/test_compare.py` | Create | Compare diff logic tests |

---

## Out of Scope

- Authentication / authorisation (future phase)
- Rate limiting (future phase)
- Docker / deployment config (future phase)
- Analytics refresh from Kore.ai (future phase)
- LLM fallback chain (future phase)
- Database migration from JSON (future phase)

---

## Success Criteria

1. App starts cleanly on a fresh machine with no `data/` directory
2. Health bar shows red on first run, guides admin to configure AI model in < 2 minutes
3. Admin can switch AI providers from any machine without touching a file or terminal
4. Candidate submits a bot export and sees a live progress indicator powered by BackgroundTasks + polling
5. Plagiarism flag appears on admin review when a duplicate is detected
6. Admin compare shows a clear score table for two submissions using `?left=&right=` params
7. `pytest tests/ -v` passes with 0 failures
8. Zero emojis anywhere in the UI — Lucide icons only
9. No technical jargon in any user-facing message
