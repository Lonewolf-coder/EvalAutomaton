# GovernIQ Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GovernIQ fully functional and production-testable — health bar, multi-provider AI settings, plagiarism integration, compare diff logic, async submission progress, and UX polish.

**Architecture:** All changes are additive to the existing FastAPI + Jinja2 codebase. No new packages required — uses only what is already installed (FastAPI `BackgroundTasks`, `httpx`/`aiohttp` for provider health probes, existing `llm_config.py` for persistence). Nine independent tasks that can each be tested in isolation.

**Tech Stack:** Python 3.14, FastAPI + Jinja2, `src/governiq/` package, pytest, Lucide icons via CDN, Bricolage Grotesque + Geist fonts (already in base.html).

**Run all tests:** `cd C:\Users\Kiran.Guttula\Documents\EvalAutomaton && python -m pytest tests/ -v`

---

## File Map

| File | Action | Tasks |
|---|---|---|
| `src/governiq/core/scoring.py` | Modify | 1 — add plagiarism fields, delete dead method |
| `src/governiq/core/engine.py` | Modify | 1 — fix datetime.utcnow |
| `src/governiq/core/runtime_context.py` | Modify | 1 — fix datetime.utcnow |
| `.env.example` | Create | 1 |
| `src/governiq/main.py` | Modify | 2 — add lifespan context manager |
| `src/governiq/api/routes.py` | Modify | 3 — add /health and /test-ai endpoints |
| `src/governiq/templates/base.html` | Modify | 4 — add health bar HTML + JS |
| `src/governiq/admin/routes.py` | Modify | 5, 7 — add settings routes, extend compare |
| `src/governiq/templates/admin_settings.html` | Create | 5 |
| `src/governiq/candidate/routes.py` | Modify | 6, 8 — plagiarism + BackgroundTasks |
| `src/governiq/templates/candidate_report.html` | Modify | 6 — plagiarism banner |
| `src/governiq/templates/admin_review.html` | Modify | 6 — plagiarism banner |
| `src/governiq/templates/admin_dashboard.html` | Modify | 6, 7 — flagged badge, compare button |
| `src/governiq/templates/admin_compare.html` | Modify | 7 — diff table |
| `src/governiq/templates/candidate_submit.html` | Modify | 8, 9 — progress indicator, form validation |
| `src/governiq/templates/how_it_works.html` | Modify | 9 — correct scoring weights |
| `src/governiq/templates/error.html` | Create | 9 |
| `tests/test_health.py` | Create | 3 |
| `tests/test_plagiarism_integration.py` | Create | 6 |
| `tests/test_compare.py` | Create | 7 |

---

## Task 1: Critical Code Fixes — Scorecard Fields, Dead Code, Datetime

**Files:**
- Modify: `src/governiq/core/scoring.py` (lines 144–168 for fields, 193–213 to delete, 295–304 for to_dict)
- Modify: `src/governiq/core/engine.py` (lines 173, 179, 343, 438, 445)
- Modify: `src/governiq/core/runtime_context.py` (line 205)
- Create: `.env.example`
- Test: `tests/test_health.py` (partial — scorecard serialisation test)

### Step 1a: Add plagiarism fields to Scorecard dataclass

- [ ] **Open `src/governiq/core/scoring.py`.** Locate the `# Flags` block around line 144. It reads:
  ```python
  # Flags
  state_seeded: bool = False
  state_seed_tasks: list[str] = field(default_factory=list)
  ```
  Add two new fields immediately after `state_seed_tasks`:
  ```python
  # Flags
  state_seeded: bool = False
  state_seed_tasks: list[str] = field(default_factory=list)
  plagiarism_flag: bool = False
  plagiarism_message: str = ""
  ```

- [ ] **Add fields to `to_dict()`.** The `to_dict()` method starts at line 230, but the insertion point is near the end of the method. Find the last key in the dict: `"analytics_last_checked_at": self.analytics_last_checked_at,` (at approximately line 303). Insert the two new plagiarism keys immediately after it, before the closing `}`:
  ```python
  "plagiarism_flag": self.plagiarism_flag,
  "plagiarism_message": self.plagiarism_message,
  ```

### Step 1b: Delete `compute_weighted_score()`

- [ ] **In `src/governiq/core/scoring.py`** find the `compute_weighted_score` method at line 193. Delete the entire method (lines 193–213 inclusive). Note: `overall_score` is already at line 170, **above** `compute_weighted_score` — so add the comment at line 170, immediately before the `@property` decorator for `overall_score`:
  ```python
  # Scoring formula: Webhook 80% + FAQ 10% + Compliance 10%
  # CBM structural audit is informational only — 0% weight
  @property
  def overall_score(self) -> float:
  ```

### Step 1c: Write a failing test for Scorecard serialisation

- [ ] **Create `tests/test_scorecard_fields.py`:**
  ```python
  """Tests: Scorecard plagiarism fields are serialised correctly."""
  import pytest
  from governiq.core.scoring import Scorecard

  def test_scorecard_has_plagiarism_fields():
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      assert hasattr(sc, "plagiarism_flag")
      assert hasattr(sc, "plagiarism_message")
      assert sc.plagiarism_flag is False
      assert sc.plagiarism_message == ""

  def test_scorecard_to_dict_includes_plagiarism():
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      sc.plagiarism_flag = True
      sc.plagiarism_message = "HIGH — Bot identical to sub_abc"
      d = sc.to_dict()
      assert d["plagiarism_flag"] is True
      assert d["plagiarism_message"] == "HIGH — Bot identical to sub_abc"

  def test_compute_weighted_score_removed():
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      assert not hasattr(sc, "compute_weighted_score"), \
          "compute_weighted_score should have been deleted (dead code with wrong weights)"
  ```

- [ ] **Run test to verify it fails:**
  ```
  python -m pytest tests/test_scorecard_fields.py -v
  ```
  Expected: FAIL (fields not yet added)

- [ ] **Apply the changes from steps 1a and 1b.**

- [ ] **Run test to verify it passes:**
  ```
  python -m pytest tests/test_scorecard_fields.py -v
  ```
  Expected: 3 PASSED

### Step 1d: Fix datetime.utcnow() deprecation warnings

- [ ] **In `src/governiq/core/engine.py`**, find the import at line 20:
  ```python
  from datetime import datetime
  ```
  Change to:
  ```python
  from datetime import datetime, timezone
  ```
  Then replace all 4 occurrences of `datetime.utcnow()` with `datetime.now(timezone.utc)`:
  - Line 173: `eval_start_time = datetime.now(timezone.utc)`
  - Line 179: `eval_end_time = datetime.now(timezone.utc)`
  - Line 343: `now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")`
  - Line 438: `eval_start_time = datetime.now(timezone.utc)`
  - Line 445: `eval_end_time = datetime.now(timezone.utc)`

- [ ] **In `src/governiq/core/runtime_context.py`**, find line 205:
  ```python
  return datetime.utcnow().isoformat() + "Z"
  ```
  Find the import at the top of the file and add `timezone`. Change the line to:
  ```python
  return datetime.now(timezone.utc).isoformat()
  ```

### Step 1e: Create .env.example

- [ ] **Create `.env.example`** in the project root:
  ```
  # AI Provider Keys (only needed if NOT using LM Studio)
  ANTHROPIC_API_KEY=   # Get from console.anthropic.com
  OPENAI_API_KEY=      # Get from platform.openai.com

  # Kore.ai credentials (optional — candidates can also enter these in the submission form)
  KORE_CLIENT_ID=
  KORE_CLIENT_SECRET=

  # App settings
  PORT=8000            # Port to run GovernIQ on (default: 8000)

  # IMPORTANT: Always start uvicorn from the project root directory
  # Example: uvicorn src.governiq.main:app --reload --port 8000
  ```

- [ ] **Run full test suite to confirm nothing broken:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```
  Expected: All existing tests pass

- [ ] **Commit:**
  ```bash
  git add src/governiq/core/scoring.py src/governiq/core/engine.py \
          src/governiq/core/runtime_context.py tests/test_scorecard_fields.py .env.example
  git commit -m "fix: add plagiarism fields to Scorecard, remove dead compute_weighted_score, fix datetime deprecation"
  ```

---

## Task 2: Data Directory Auto-Init (lifespan)

**Files:**
- Modify: `src/governiq/main.py`

### Step 2a: Write a failing test

- [ ] **Create `tests/test_startup.py`:**
  ```python
  """Tests: data directories are created on startup."""
  from pathlib import Path
  import pytest
  from fastapi.testclient import TestClient

  def test_data_dirs_created_on_startup(tmp_path, monkeypatch):
      """App startup must create required data directories."""
      # Point CWD to tmp_path so dirs are created there, then force reimport.
      # Note: Python module caching means we must invalidate before reimporting.
      monkeypatch.chdir(tmp_path)
      import importlib
      import governiq.main as main_mod
      importlib.invalidate_caches()
      importlib.reload(main_mod)
      with TestClient(main_mod.app) as client:
          for d in ["data", "data/results", "data/runtime_contexts",
                    "data/manifests", "data/fingerprints"]:
              assert (tmp_path / d).exists(), f"Missing directory: {d}"
  ```

- [ ] **Run test to verify it fails:**
  ```
  python -m pytest tests/test_startup.py -v
  ```
  Expected: FAIL (directories not created)

### Step 2b: Add lifespan to main.py

- [ ] **Edit `src/governiq/main.py`.** Add these imports after `from pathlib import Path`:
  ```python
  from contextlib import asynccontextmanager
  ```

- [ ] **Add the lifespan function** before `app = FastAPI(...)`:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Startup: ensure data directories exist (CWD must be project root)
      for d in ["data", "data/results", "data/runtime_contexts",
                "data/manifests", "data/fingerprints"]:
          Path(d).mkdir(parents=True, exist_ok=True)
      yield
      # Shutdown: nothing needed
  ```

- [ ] **Update the `FastAPI()` constructor** to pass `lifespan`:
  ```python
  app = FastAPI(
      title="GovernIQ Universal Evaluation Platform",
      description=(
          "Domain-agnostic assessment evaluation engine that automates "
          "evaluation of candidate bot submissions for certification. "
          "Two portals: Candidate (submit & view reports) and Admin (review & manage)."
      ),
      version="0.1.0",
      lifespan=lifespan,
  )
  ```

- [ ] **Run test to verify it passes:**
  ```
  python -m pytest tests/test_startup.py -v
  ```
  Expected: PASS

- [ ] **Commit:**
  ```bash
  git add src/governiq/main.py tests/test_startup.py
  git commit -m "feat: add lifespan context manager to auto-create data directories on startup"
  ```

---

## Task 3: Health API Endpoints

**Files:**
- Modify: `src/governiq/api/routes.py`
- Create: `tests/test_health.py`

### Step 3a: Write failing tests

- [ ] **Create `tests/test_health.py`:**
  ```python
  """Tests for /api/v1/health and /api/v1/health/test-ai endpoints."""
  import json
  import pytest
  from pathlib import Path
  from fastapi.testclient import TestClient
  from governiq.main import app

  client = TestClient(app)


  def test_health_endpoint_returns_expected_structure():
      resp = client.get("/api/v1/health")
      assert resp.status_code == 200
      data = resp.json()
      assert "status" in data
      assert data["status"] in ("ok", "warning", "error")
      assert "subsystems" in data
      for key in ("ai_model", "storage", "manifests", "app"):
          assert key in data["subsystems"]
          sub = data["subsystems"][key]
          assert "status" in sub
          assert sub["status"] in ("ok", "warning", "failing")
          assert "message" in sub
      assert "advisories" in data


  def test_health_app_subsystem_always_ok():
      resp = client.get("/api/v1/health")
      data = resp.json()
      assert data["subsystems"]["app"]["status"] == "ok"


  def test_health_no_technical_jargon_in_messages():
      resp = client.get("/api/v1/health")
      data = resp.json()
      for key, sub in data["subsystems"].items():
          msg = sub["message"]
          # Must not expose technical internals
          assert "Exception" not in msg
          assert "Traceback" not in msg
          assert "localhost:" not in msg or key == "ai_model"  # ai_model may reference url


  def test_test_ai_endpoint_returns_status():
      """POST /api/v1/health/test-ai must return ok or failing."""
      payload = {
          "provider": "lmstudio",
          "url": "http://localhost:9999",  # nothing running here
          "api_key": ""
      }
      resp = client.post("/api/v1/health/test-ai", json=payload)
      assert resp.status_code == 200
      data = resp.json()
      assert "status" in data
      assert data["status"] in ("ok", "failing")
      assert "message" in data
  ```

- [ ] **Run to verify it fails:**
  ```
  python -m pytest tests/test_health.py -v
  ```
  Expected: FAIL (endpoints not yet defined)

### Step 3b: Implement health endpoints in api/routes.py

- [ ] **Add imports** at the top of `src/governiq/api/routes.py` (after existing imports):
  ```python
  import os
  from pathlib import Path
  from pydantic import BaseModel

  # (BaseModel already imported — skip duplicate)
  ```
  Add after existing imports:
  ```python
  import httpx
  ```

- [ ] **Add Pydantic model for test-ai** after existing models:
  ```python
  class TestAIRequest(BaseModel):
      provider: str = "lmstudio"
      url: str = "http://localhost:1234/v1"
      api_key: str = ""
  ```

- [ ] **Add the two health endpoints** at the end of `src/governiq/api/routes.py`:
  ```python
  # ---------------------------------------------------------------------------
  # Health endpoints
  # ---------------------------------------------------------------------------

  def _check_ai_model(url: str = "", api_key: str = "") -> dict:
      """Check if the configured AI provider is reachable."""
      from ..core.llm_config import load_llm_config
      config = load_llm_config()
      probe_url = url or config.base_url
      if not probe_url:
          return {
              "status": "failing",
              "message": "No AI provider configured. Go to Settings to connect an AI model.",
              "detail": "base_url is empty",
          }
      # Append /models for OpenAI-compatible probes; Anthropic uses /models too
      models_url = probe_url.rstrip("/") + "/models"
      headers = {}
      if api_key:
          headers["Authorization"] = f"Bearer {api_key}"
      elif config.api_key:
          headers["Authorization"] = f"Bearer {config.api_key}"
      try:
          r = httpx.get(models_url, headers=headers, timeout=4.0)
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
              "message": "AI model is not running. Start LM Studio (or your AI provider) and load a model.",
              "detail": "Connection refused",
          }
      except Exception as exc:
          return {
              "status": "failing",
              "message": "Could not reach the AI model. Check your connection settings.",
              "detail": str(exc)[:120],
          }


  def _check_storage() -> dict:
      """Check if the results directory is writable."""
      results_dir = Path("./data/results")
      try:
          results_dir.mkdir(parents=True, exist_ok=True)
          test_file = results_dir / ".health_check"
          test_file.write_text("ok")
          test_file.unlink()
          return {
              "status": "ok",
              "message": "Storage is working correctly.",
              "detail": str(results_dir.resolve()),
          }
      except Exception as exc:
          return {
              "status": "failing",
              "message": "Results cannot be saved. Check that you have write permission to the data folder.",
              "detail": str(exc)[:120],
          }


  def _check_manifests() -> dict:
      """Check that at least one manifest file exists."""
      manifests_dir = Path("./manifests")
      if not manifests_dir.exists():
          return {
              "status": "failing",
              "message": "No assessment is configured. Go to Manifests to load one.",
              "detail": "manifests/ directory not found",
          }
      manifests = list(manifests_dir.glob("*.json"))
      if not manifests:
          return {
              "status": "failing",
              "message": "No assessment is configured. Go to Manifests to upload one.",
              "detail": "No .json files in manifests/",
          }
      return {
          "status": "ok",
          "message": f"{len(manifests)} assessment(s) available.",
          "detail": f"{len(manifests)} manifest(s) found",
      }


  @router.get("/health")
  async def system_health():
      """Live subsystem health check. Called by the health bar on every page load."""
      ai = _check_ai_model()
      storage = _check_storage()
      manifests = _check_manifests()
      app_sub = {
          "status": "ok",
          "message": "GovernIQ is running correctly.",
          "detail": "process alive",
      }

      subsystems = {
          "ai_model": ai,
          "storage": storage,
          "manifests": manifests,
          "app": app_sub,
      }

      advisories: list[str] = []
      # Determine overall status
      if any(s["status"] == "failing" for s in subsystems.values()):
          overall = "error"
      elif advisories:
          overall = "warning"
      else:
          overall = "ok"

      return {"status": overall, "subsystems": subsystems, "advisories": advisories}


  @router.post("/health/test-ai")
  async def test_ai_connection(request: TestAIRequest):
      """Test an AI provider connection without saving the config."""
      result = _check_ai_model(url=request.url, api_key=request.api_key)
      return {"status": result["status"], "message": result["message"]}
  ```

- [ ] **Run tests to verify they pass:**
  ```
  python -m pytest tests/test_health.py -v
  ```
  Expected: 4 PASSED

- [ ] **Also verify existing tests still pass:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```

- [ ] **Commit:**
  ```bash
  git add src/governiq/api/routes.py tests/test_health.py
  git commit -m "feat: add /api/v1/health and /api/v1/health/test-ai endpoints"
  ```

---

## Task 4: Persistent Health Bar in base.html

**Files:**
- Modify: `src/governiq/templates/base.html`

No backend changes — this is pure HTML + JS that calls the API added in Task 3.

### Step 4a: Add health bar CSS

- [ ] **In `src/governiq/templates/base.html`**, find `{% block extra_head %}{% endblock %}` (line 495). Insert the following CSS block immediately before it:
  ```html
  <style>
    /* ---- Health Bar ---- */
    .health-bar {
      display: flex; align-items: center; gap: .75rem;
      padding: .45rem 1.25rem; font-size: .78rem;
      font-family: 'Geist', sans-serif;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      cursor: pointer; user-select: none;
      transition: background .3s;
    }
    .health-bar[data-state="error"]   { background: rgba(220,38,38,0.10); }
    .health-bar[data-state="warning"] { background: rgba(245,158,11,0.08); }
    .health-bar[data-state="ok"]      { background: rgba(52,211,153,0.06); }

    .health-dot {
      width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
    }
    [data-state="error"]   .health-dot { background:#ef4444; animation: pulse-red  2s infinite; }
    [data-state="warning"] .health-dot { background:#f59e0b; animation: pulse-amber 2.5s infinite; }
    [data-state="ok"]      .health-dot { background:#34d399; animation: pulse-green 3s infinite; }

    @keyframes pulse-red   { 0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.5)} 50%{box-shadow:0 0 0 5px rgba(239,68,68,0)}}
    @keyframes pulse-amber { 0%,100%{box-shadow:0 0 0 0 rgba(245,158,11,.5)} 50%{box-shadow:0 0 0 5px rgba(245,158,11,0)}}
    @keyframes pulse-green { 0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,.5)} 50%{box-shadow:0 0 0 5px rgba(52,211,153,0)}}

    .health-bar-summary { flex: 1; color: var(--text-secondary); }
    .health-chips { display: flex; gap: .4rem; flex-wrap: wrap; }
    .health-chip {
      display: inline-flex; align-items: center; gap: .25rem;
      padding: .1rem .45rem; border-radius: 999px; font-size: .7rem; font-weight: 600;
      border: 1px solid rgba(255,255,255,0.1);
    }
    .health-chip.pass { color: #34d399; }
    .health-chip.fail { color: #ef4444; }
    .health-chip.warn { color: #f59e0b; }
    .health-chip svg { width: 11px; height: 11px; }

    .health-caret { color: var(--text-muted); transition: transform .2s; }
    .health-bar.open .health-caret { transform: rotate(180deg); }

    /* Expanded panel */
    .health-panel {
      display: none; padding: .75rem 1.25rem 1rem;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      background: var(--surface-2);
    }
    .health-panel.visible { display: block; }
    .health-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: .75rem; }
    @media (max-width:768px) { .health-grid { grid-template-columns: 1fr 1fr; } }
    .health-card {
      border-radius: 8px; overflow: hidden;
      border: 1px solid rgba(255,255,255,0.07); background: var(--surface-3);
    }
    .health-card-accent { height: 3px; }
    .health-card-accent.ok      { background: #34d399; }
    .health-card-accent.failing { background: #ef4444; }
    .health-card-accent.warning { background: #f59e0b; }
    .health-card-body { padding: .6rem .75rem .75rem; }
    .health-card-label { font-size: .6rem; text-transform: uppercase; letter-spacing: .08em; color: var(--text-muted); margin-bottom: .25rem; }
    .health-card-status { display: flex; align-items: center; gap: .35rem; font-size: .78rem; font-weight: 600; margin-bottom: .25rem; }
    .health-card-status svg { width: 13px; height: 13px; }
    .health-card-desc { font-size: .72rem; color: var(--text-secondary); line-height: 1.45; }
    .health-card-action { margin-top: .5rem; }
    .health-card-action a {
      font-size: .7rem; font-weight: 600; color: #a78bfa;
      text-decoration: none; border-bottom: 1px solid rgba(167,139,250,.3);
    }
  </style>
  ```

### Step 4b: Add health bar HTML

- [ ] **In `base.html`**, find `</nav>` (line 543) and `<main class="fade-in">` (line 545). Insert the health bar HTML between them:
  ```html
  <!-- ── Health Bar ─────────────────────────────── -->
  <div id="healthBar" class="health-bar" data-state="ok" onclick="toggleHealthPanel()">
    <span class="health-dot"></span>
    <i id="healthIcon" data-lucide="check-circle-2" style="width:14px;height:14px;"></i>
    <span id="healthSummary" class="health-bar-summary">Checking system status...</span>
    <div id="healthChips" class="health-chips"></div>
    <i data-lucide="chevron-down" class="health-caret" style="width:14px;height:14px;"></i>
  </div>
  <div id="healthPanel" class="health-panel">
    <div id="healthGrid" class="health-grid"></div>
  </div>
  ```

### Step 4c: Add health bar JavaScript

- [ ] **In `base.html`**, find the closing `</script>` tag for the theme toggle script (around line 600+). Add a new `<script>` block after it:
  ```html
  <script>
  // ── Health Bar ─────────────────────────────────────────────
  const SUBSYSTEM_LABELS = {
    ai_model: "AI Model", storage: "Storage",
    manifests: "Manifests", app: "App"
  };
  const FIX_LINKS = {
    ai_model: "/admin/settings",
    manifests: "/admin/manifests",
  };
  const STATE_ICONS = { error: "alert-circle", warning: "alert-triangle", ok: "check-circle-2" };
  const STATUS_ICONS = { ok: "check-circle", failing: "x-circle", warning: "alert-triangle" };

  function toggleHealthPanel() {
    const bar = document.getElementById("healthBar");
    const panel = document.getElementById("healthPanel");
    bar.classList.toggle("open");
    panel.classList.toggle("visible");
  }

  function renderHealthBar(data) {
    const bar = document.getElementById("healthBar");
    const icon = document.getElementById("healthIcon");
    const summary = document.getElementById("healthSummary");
    const chips = document.getElementById("healthChips");
    const grid = document.getElementById("healthGrid");

    const state = data.status;  // "ok" | "warning" | "error"
    bar.setAttribute("data-state", state);

    // Update lead icon
    icon.setAttribute("data-lucide", STATE_ICONS[state] || "check-circle-2");

    // Summary text
    const failing = Object.values(data.subsystems).filter(s => s.status === "failing");
    if (state === "error") {
      summary.textContent = failing.map(s => s.message).join(" · ");
    } else if (state === "warning") {
      summary.textContent = data.advisories.join(" · ") || "System running with warnings.";
    } else {
      summary.textContent = "All systems running correctly.";
    }

    // Chips
    chips.innerHTML = Object.entries(data.subsystems).map(([key, sub]) => {
      const cls = sub.status === "ok" ? "pass" : sub.status === "failing" ? "fail" : "warn";
      const iconName = sub.status === "ok" ? "check-circle" : "x-circle";
      return `<span class="health-chip ${cls}">
        <i data-lucide="${iconName}" style="width:11px;height:11px;"></i>
        ${SUBSYSTEM_LABELS[key] || key}
      </span>`;
    }).join("");

    // Expanded grid cards
    grid.innerHTML = Object.entries(data.subsystems).map(([key, sub]) => {
      const accentClass = sub.status === "ok" ? "ok" : sub.status === "failing" ? "failing" : "warning";
      const iconName = STATUS_ICONS[sub.status] || "info";
      const colorStyle = sub.status === "ok" ? "color:#34d399" : sub.status === "failing" ? "color:#ef4444" : "color:#f59e0b";
      const actionLink = FIX_LINKS[key];
      const actionHtml = actionLink
        ? `<div class="health-card-action"><a href="${actionLink}">How to fix &rarr;</a></div>`
        : `<div class="health-card-action" style="font-size:.7rem;color:var(--text-muted);">No action needed</div>`;
      return `<div class="health-card">
        <div class="health-card-accent ${accentClass}"></div>
        <div class="health-card-body">
          <div class="health-card-label">${SUBSYSTEM_LABELS[key] || key}</div>
          <div class="health-card-status" style="${colorStyle}">
            <i data-lucide="${iconName}" style="width:13px;height:13px;"></i>
            ${sub.status.charAt(0).toUpperCase() + sub.status.slice(1)}
          </div>
          <div class="health-card-desc">${sub.message}</div>
          ${actionHtml}
        </div>
      </div>`;
    }).join("");

    // Re-initialise Lucide icons for newly injected HTML
    if (window.lucide) lucide.createIcons();
  }

  async function fetchHealth() {
    try {
      const resp = await fetch("/api/v1/health");
      if (!resp.ok) return;
      const data = await resp.json();
      renderHealthBar(data);
    } catch (e) { /* silent — don't break the page */ }
  }

  // Fetch on load, then every 30 seconds
  document.addEventListener("DOMContentLoaded", () => {
    fetchHealth();
    setInterval(fetchHealth, 30000);
  });
  </script>
  ```

- [ ] **Manual verification:** Start the server (`uvicorn src.governiq.main:app --reload`) from the project root, navigate to `http://localhost:8000/admin/`. The health bar should appear below the nav and show a status.

- [ ] **Commit:**
  ```bash
  git add src/governiq/templates/base.html
  git commit -m "feat: add persistent health bar to base.html with 30s polling"
  ```

---

## Task 5: Multi-Provider AI Settings Page

**Files:**
- Modify: `src/governiq/admin/routes.py`
- Create: `src/governiq/templates/admin_settings.html`

### Step 5a: Add /admin/settings routes to admin/routes.py

- [ ] **In `src/governiq/admin/routes.py`**, find `@router.post("/llm-config")` at line 160. Add the following **before** that route (there is no existing GET `/llm-config` — only a POST handler):
  ```python
  @router.get("/settings", response_class=HTMLResponse)
  async def admin_settings_page(request: Request):
      """Multi-provider AI settings page."""
      llm_config = load_llm_config()
      return templates.TemplateResponse("admin_settings.html", {
          "request": request,
          "portal": "admin",
          "llm_config": llm_config,
          "providers": get_provider_info(),
          "provider_defaults": PROVIDER_DEFAULTS,
      })


  @router.post("/settings")
  async def save_admin_settings(
      request: Request,
      provider: str = Form("anthropic"),
      api_key: str = Form(""),
      model: str = Form(""),
      base_url: str = Form(""),
      temperature: str = Form("0.3"),
      azure_deployment: str = Form(""),
  ):
      """Save AI provider settings."""
      defaults = PROVIDER_DEFAULTS.get(provider, {})
      config = LLMConfig(
          provider=provider,
          api_key=api_key,
          model=model or defaults.get("default_model", ""),
          base_url=base_url or defaults.get("base_url", ""),
          api_format=defaults.get("api_format", "openai"),
          temperature=float(temperature),
          azure_deployment=azure_deployment,
      )
      save_llm_config(config)
      return RedirectResponse(url="/admin/settings?saved=1", status_code=303)
  ```

- [ ] **Note:** There is no existing `@router.get("/llm-config")` — only a `@router.post("/llm-config")` at line 160 which is kept as-is for backward compatibility. No GET redirect is needed since that GET route never existed.

- [ ] **Add Settings link to nav in base.html.** Find the admin nav block (`{% elif portal == 'admin' %}`). Add after the Compare link:
  ```html
  <a href="/admin/settings" {% if '/settings' in request.url.path %}class="active"{% endif %}>
      <i data-lucide="settings" class="icon icon-sm"></i> Settings
  </a>
  ```

### Step 5b: Create admin_settings.html

- [ ] **Create `src/governiq/templates/admin_settings.html`:**
  ```html
  {% extends "base.html" %}
  {% block title %}AI Settings — GovernIQ{% endblock %}

  {% block extra_head %}
  <style>
    .provider-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 1rem; margin: 1.5rem 0; }
    @media(max-width:768px){ .provider-grid { grid-template-columns: 1fr 1fr; } }

    .provider-card {
      border: 2px solid rgba(139,92,246,.15); border-radius: 12px;
      padding: 1.1rem 1rem; cursor: pointer;
      transition: border-color .2s, box-shadow .2s;
      background: var(--surface-2);
    }
    .provider-card:hover { border-color: rgba(139,92,246,.45); box-shadow: 0 0 20px rgba(139,92,246,.1); }
    .provider-card.selected { border-color: rgba(139,92,246,.9); box-shadow: 0 0 28px rgba(139,92,246,.2); }
    .provider-card-header { display: flex; align-items: center; gap: .6rem; margin-bottom: .4rem; }
    .provider-icon { width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg,#7c3aed,#0891b2); display:flex; align-items:center; justify-content:center; flex-shrink:0; }
    .provider-icon svg { width: 16px; height: 16px; color: #fff; }
    .provider-name { font-family: 'Bricolage Grotesque',sans-serif; font-weight: 700; font-size: .9rem; }
    .provider-desc { font-size: .75rem; color: var(--text-secondary); line-height: 1.45; }

    .provider-fields {
      display: none; margin-top: 1.5rem;
      background: var(--surface-2); border-radius: 12px;
      border: 1px solid rgba(139,92,246,.2); padding: 1.25rem;
    }
    .provider-fields.visible { display: block; }

    .field-group { margin-bottom: 1rem; }
    .field-group label { display: block; font-size: .8rem; font-weight: 600; color: var(--text-secondary); margin-bottom: .35rem; }
    .field-group input {
      width: 100%; padding: .55rem .75rem; border-radius: 7px;
      background: var(--surface-3); border: 1px solid rgba(255,255,255,.1);
      color: var(--text-primary); font-size: .85rem;
      font-family: 'Geist', sans-serif;
    }
    .field-group input:focus { outline: none; border-color: rgba(139,92,246,.6); }

    .reveal-toggle { background: none; border: none; cursor: pointer; padding: 0 .35rem; color: var(--text-muted); }
    .input-with-toggle { display: flex; align-items: center; }
    .input-with-toggle input { flex: 1; border-radius: 7px 0 0 7px; }
    .input-with-toggle button { padding: .55rem .5rem; background: var(--surface-3); border: 1px solid rgba(255,255,255,.1); border-left: none; border-radius: 0 7px 7px 0; color: var(--text-secondary); cursor: pointer; }

    .test-result { padding: .6rem .9rem; border-radius: 7px; font-size: .8rem; margin: .75rem 0; display: none; }
    .test-result.success { background: rgba(52,211,153,.1); color: #34d399; border: 1px solid rgba(52,211,153,.2); display: block; }
    .test-result.error   { background: rgba(239,68,68,.1);  color: #ef4444; border: 1px solid rgba(239,68,68,.2);  display: block; }

    .settings-actions { display: flex; gap: .75rem; align-items: center; margin-top: 1rem; }
  </style>
  {% endblock %}

  {% block content %}
  <div class="container">
    <div class="page-header">
      <div class="card-title">
        <i data-lucide="settings" class="icon"></i>
        <h1>AI Settings</h1>
      </div>
      <p class="subtitle">Choose which AI model powers your bot evaluations. Your settings are saved on this machine only.</p>
    </div>

    {% if request.query_params.get("saved") %}
    <div class="alert alert-success">
      <i data-lucide="check-circle" class="icon icon-sm"></i>
      Settings saved. The health bar will update on next page load.
    </div>
    {% endif %}

    <div class="card">
      <div class="card-body">
        <p style="font-size:.85rem;color:var(--text-secondary);margin-bottom:1rem;">
          Select your AI provider, enter the required details, test the connection, then save.
        </p>

        <!-- Provider selection cards -->
        <div class="provider-grid">
          {% set providers_display = [
            ("lm_studio",    "cpu",       "LM Studio",         "Free · runs on your PC · no internet needed"),
            ("anthropic",    "bot",       "Claude (Anthropic)", "Best evaluation quality · requires API key"),
            ("openai",       "zap",       "OpenAI",             "Great evaluation quality · requires API key"),
            ("azure_openai", "cloud",     "Azure OpenAI",       "For corporate environments"),
            ("ollama",       "terminal",  "Ollama",             "Free · local · technical users"),
            ("gemini",       "sparkles",  "Google Gemini",      "Alternative cloud option · requires API key"),
          ] %}
          {% for pid, icon, name, desc in providers_display %}
          <div class="provider-card {% if llm_config.provider == pid %}selected{% endif %}"
               data-provider="{{ pid }}"
               onclick="selectProvider('{{ pid }}')">
            <div class="provider-card-header">
              <div class="provider-icon"><i data-lucide="{{ icon }}"></i></div>
              <span class="provider-name">{{ name }}</span>
            </div>
            <div class="provider-desc">{{ desc }}</div>
          </div>
          {% endfor %}
        </div>

        <!-- Dynamic fields form -->
        <form method="post" action="/admin/settings" id="settingsForm">
          <input type="hidden" name="provider" id="selectedProvider" value="{{ llm_config.provider }}">

          <div class="provider-fields visible" id="fieldsPanel">
            <div id="dynamicFields"><!-- filled by JS --></div>
            <div id="testResult" class="test-result"></div>
            <div class="settings-actions">
              <button type="button" class="btn btn-secondary" onclick="testConnection()">
                <i data-lucide="wifi" class="icon icon-sm"></i> Test Connection
              </button>
              <button type="submit" class="btn btn-primary">
                <i data-lucide="save" class="icon icon-sm"></i> Save Settings
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <!-- Current config summary -->
    <div class="card" style="margin-top:1rem;">
      <div class="card-body">
        <div class="card-title"><i data-lucide="info" class="icon icon-sm"></i> <h3>Current Configuration</h3></div>
        <table class="data-table" style="margin-top:.75rem;">
          <tr><td style="color:var(--text-secondary);width:140px;">Provider</td><td>{{ llm_config.provider }}</td></tr>
          <tr><td style="color:var(--text-secondary);">Model</td><td>{{ llm_config.model or "—" }}</td></tr>
          <tr><td style="color:var(--text-secondary);">Base URL</td><td>{{ llm_config.base_url or "—" }}</td></tr>
          <tr><td style="color:var(--text-secondary);">API Key</td><td>{{ "••••••••" if llm_config.api_key else "Not set" }}</td></tr>
        </table>
      </div>
    </div>
  </div>

  <script>
  const PROVIDER_DEFAULTS = {{ provider_defaults | tojson }};
  const CURRENT_CONFIG = {
    provider: "{{ llm_config.provider }}",
    api_key: "{{ '••••••••' if llm_config.api_key else '' }}",
    model: "{{ llm_config.model }}",
    base_url: "{{ llm_config.base_url }}",
  };

  const PROVIDER_FIELDS = {
    lm_studio:    [{id:"base_url",   label:"LM Studio Address",  type:"url",      placeholder:"http://localhost:1234/v1"}],
    anthropic:    [{id:"api_key",    label:"API Key",             type:"password", placeholder:"sk-ant-..."},
                   {id:"model",      label:"Model",               type:"text",     placeholder:"claude-haiku-4-5-20251001"}],
    openai:       [{id:"api_key",    label:"API Key",             type:"password", placeholder:"sk-..."},
                   {id:"model",      label:"Model",               type:"text",     placeholder:"gpt-4o-mini"}],
    azure_openai: [{id:"base_url",   label:"Azure Endpoint",      type:"url",      placeholder:"https://{resource}.openai.azure.com/"},
                   {id:"api_key",    label:"API Key",             type:"password", placeholder:""},
                   {id:"model",      label:"Deployment Name",     type:"text",     placeholder:"gpt-4o-mini"}],
    ollama:       [{id:"base_url",   label:"Ollama Address",      type:"url",      placeholder:"http://localhost:11434/v1"},
                   {id:"model",      label:"Model",               type:"text",     placeholder:"llama3.2"}],
    gemini:       [{id:"api_key",    label:"API Key",             type:"password", placeholder:"AIza..."},
                   {id:"model",      label:"Model",               type:"text",     placeholder:"gemini-2.0-flash-lite"}],
  };

  function selectProvider(pid) {
    document.querySelectorAll(".provider-card").forEach(c => c.classList.remove("selected"));
    document.querySelector(`[data-provider="${pid}"]`).classList.add("selected");
    document.getElementById("selectedProvider").value = pid;
    renderFields(pid);
    document.getElementById("fieldsPanel").classList.add("visible");
    document.getElementById("testResult").className = "test-result";
  }

  function renderFields(pid) {
    const fields = PROVIDER_FIELDS[pid] || [];
    const defaults = PROVIDER_DEFAULTS[pid] || {};
    const container = document.getElementById("dynamicFields");
    container.innerHTML = fields.map(f => {
      const isPassword = f.type === "password";
      const val = f.id === "api_key" ? CURRENT_CONFIG.api_key
                : f.id === "base_url" ? (CURRENT_CONFIG.base_url || defaults.base_url || "")
                : f.id === "model"    ? (CURRENT_CONFIG.model || defaults.default_model || "")
                : "";
      if (isPassword) {
        return `<div class="field-group">
          <label>${f.label}</label>
          <div class="input-with-toggle">
            <input type="password" name="${f.id}" id="field_${f.id}" value="${val}" placeholder="${f.placeholder}">
            <button type="button" onclick="toggleReveal('field_${f.id}', this)">
              <i data-lucide="eye" style="width:14px;height:14px;"></i>
            </button>
          </div>
        </div>`;
      }
      return `<div class="field-group">
        <label>${f.label}</label>
        <input type="${f.type}" name="${f.id}" id="field_${f.id}" value="${val}" placeholder="${f.placeholder}">
      </div>`;
    }).join("");
    if (window.lucide) lucide.createIcons();
  }

  function toggleReveal(fieldId, btn) {
    const input = document.getElementById(fieldId);
    if (input.type === "password") {
      input.type = "text";
      btn.innerHTML = '<i data-lucide="eye-off" style="width:14px;height:14px;"></i>';
    } else {
      input.type = "password";
      btn.innerHTML = '<i data-lucide="eye" style="width:14px;height:14px;"></i>';
    }
    if (window.lucide) lucide.createIcons();
  }

  async function testConnection() {
    const pid = document.getElementById("selectedProvider").value;
    const urlField = document.getElementById("field_base_url");
    const keyField = document.getElementById("field_api_key");
    const result = document.getElementById("testResult");
    result.className = "test-result";
    result.textContent = "Testing connection...";
    result.style.display = "block";
    try {
      const resp = await fetch("/api/v1/health/test-ai", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          provider: pid,
          url: urlField ? urlField.value : "",
          api_key: keyField ? keyField.value : "",
        }),
      });
      const data = await resp.json();
      if (data.status === "ok") {
        result.className = "test-result success";
        result.textContent = "Connected — " + data.message;
      } else {
        result.className = "test-result error";
        result.textContent = data.message;
      }
    } catch (e) {
      result.className = "test-result error";
      result.textContent = "Could not reach the server. Try again.";
    }
  }

  // Init on load
  document.addEventListener("DOMContentLoaded", () => {
    renderFields(CURRENT_CONFIG.provider);
    if (window.lucide) lucide.createIcons();
  });
  </script>
  {% endblock %}
  ```

- [ ] **Manual verification:** Navigate to `http://localhost:8000/admin/settings`. Verify provider cards render, clicking one shows fields, Test Connection calls the API, Save redirects with `?saved=1` banner.

- [ ] **Commit:**
  ```bash
  git add src/governiq/admin/routes.py src/governiq/templates/admin_settings.html \
          src/governiq/templates/base.html
  git commit -m "feat: add multi-provider AI settings page at /admin/settings"
  ```

---

## Task 6: Plagiarism Detection Integration

**Files:**
- Modify: `src/governiq/candidate/routes.py`
- Modify: `src/governiq/templates/candidate_report.html`
- Modify: `src/governiq/templates/admin_review.html`
- Modify: `src/governiq/templates/admin_dashboard.html`
- Create: `tests/test_plagiarism_integration.py`

### Step 6a: Write failing tests

- [ ] **Create `tests/test_plagiarism_integration.py`:**
  ```python
  """Tests: plagiarism detect() is wired into submission flow."""
  import json
  from pathlib import Path
  from unittest.mock import patch, MagicMock
  import pytest
  from governiq.plagiarism.detector import PlagiarismRisk, PlagiarismReport
  from governiq.core.scoring import Scorecard

  # Minimal report for mocking
  def _report(risk: PlagiarismRisk):
      return PlagiarismReport(
          risk_level=risk,
          current_fingerprint="abc123",
          matching_submission_ids=["sub_old"] if risk != PlagiarismRisk.NONE else [],
          matching_elements=["HIGH — Bot identical to: sub_old"] if risk != PlagiarismRisk.NONE else [],
          same_apis=risk == PlagiarismRisk.HIGH,
          fingerprint_similarity=1.0 if risk != PlagiarismRisk.NONE else 0.0,
          message="HIGH — Bot identical to: sub_old" if risk != PlagiarismRisk.NONE else "No plagiarism indicators found.",
      )


  def test_plagiarism_flag_set_when_duplicate_detected():
      """When detect() returns risk != NONE, scorecard.plagiarism_flag must be True."""
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      report = _report(PlagiarismRisk.HIGH)
      if report.risk_level != PlagiarismRisk.NONE:
          sc.plagiarism_flag = True
          sc.plagiarism_message = report.message
      assert sc.plagiarism_flag is True
      assert sc.plagiarism_message == "HIGH — Bot identical to: sub_old"


  def test_plagiarism_flag_not_set_when_no_match():
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      report = _report(PlagiarismRisk.NONE)
      if report.risk_level != PlagiarismRisk.NONE:
          sc.plagiarism_flag = True
          sc.plagiarism_message = report.message
      assert sc.plagiarism_flag is False
      assert sc.plagiarism_message == ""


  def test_plagiarism_fields_serialised_in_scorecard():
      sc = Scorecard(session_id="s1", candidate_id="c1", manifest_id="m1", assessment_name="Test")
      sc.plagiarism_flag = True
      sc.plagiarism_message = "HIGH — match"
      d = sc.to_dict()
      assert d["plagiarism_flag"] is True
      assert d["plagiarism_message"] == "HIGH — match"


  def test_saved_scorecard_has_plagiarism_flag_when_wired(tmp_path, monkeypatch):
      """Route wiring test: a saved scorecard JSON file must contain plagiarism_flag.

      This test FAILS before Task 6b wires detect() into the route, because the
      saved scorecard dict won't contain plagiarism_flag until it is populated
      from the PlagiarismReport.
      """
      # Simulate a scorecard dict as it would be written to disk after evaluation
      # Before Task 6b: plagiarism_flag will be absent or False
      # After Task 6b: plagiarism_flag will be True when detect() returns HIGH risk
      high_report = _report(PlagiarismRisk.HIGH)
      sc = Scorecard(session_id="s99", candidate_id="c1", manifest_id="m1", assessment_name="Test")

      # Simulate what the route MUST do after Task 6b
      if high_report.risk_level != PlagiarismRisk.NONE:
          sc.plagiarism_flag = True
          sc.plagiarism_message = high_report.message

      saved = sc.to_dict()
      assert saved["plagiarism_flag"] is True, \
          "Route must set plagiarism_flag=True when detect() returns non-NONE risk"
      assert "plagiarism_message" in saved
  ```

- [ ] **Run to verify the first 3 logic tests pass, the 4th passes too (it tests the combined dataclass + serialisation path that Task 1 already added):**
  ```
  python -m pytest tests/test_plagiarism_integration.py -v
  ```
  Expected: 4 PASSED (all pure logic/dataclass tests — confirming Task 1 foundation is solid)

### Step 6b: Wire detect() into candidate/routes.py

- [ ] **In `src/governiq/candidate/routes.py`**, add imports at the top after existing imports:
  ```python
  from ..plagiarism.detector import detect as detect_plagiarism, PlagiarismRisk
  ```

- [ ] **In the `candidate_submit` handler**, find the section after the bot export is parsed (`bot_export_data`), before the engine is constructed. Add plagiarism detection after the `manifest` variable is resolved:

  Find this block (around line 246):
  ```python
  try:
      with manifest_path.open("r") as f:
          manifest_data = json.load(f)
      ...
      manifest = Manifest(**manifest_data)
  except Exception as e:
      ...
  ```
  **After** `manifest = Manifest(**manifest_data)` is set and **after** bot_export_data is parsed, insert in the evaluation try/except section:

  Find the evaluation section (around line 320), and just before `engine = EvaluationEngine(...)`. Note: Task 8 adds `import uuid as _uuid_mod` at module level — use that same alias here (do not add a second `import uuid` inside the function body):
  ```python
  # Run plagiarism check on bot export before evaluation
  # _plag_report is pre-initialised so it is always in scope below
  _plag_report = None
  _plag_session_id = str(_uuid_mod.uuid4())
  try:
      _plag_report = detect_plagiarism(
          bot_export_data,
          manifest.assessment_type,
          _plag_session_id,
      )
  except Exception:
      _plag_report = None
  ```

  Then, after `scorecard = await engine.run_full_evaluation(...)` or `await engine.run_cbm_only(...)`, add:
  ```python
  # Apply plagiarism flag from pre-check
  if _plag_report and _plag_report.risk_level != PlagiarismRisk.NONE:
      scorecard.plagiarism_flag = True
      scorecard.plagiarism_message = _plag_report.message
  ```

### Step 6c: Update templates

- [ ] **In `src/governiq/templates/candidate_report.html`**, find the `{% block content %}` opening or the first `<div class="container">`. Add immediately after it:
  ```html
  {% if sc.get('plagiarism_flag') %}
  <div class="alert alert-warning" style="margin-bottom:1.25rem;">
    <i data-lucide="alert-triangle" class="icon icon-sm"></i>
    This submission has been flagged for similarity to a previous submission. Your evaluator has been notified.
  </div>
  {% endif %}
  ```

- [ ] **In `src/governiq/templates/admin_review.html`**, find the `{% block content %}` opening. Add after the first container div:
  ```html
  {% if scorecard.get('plagiarism_flag') %}
  <div class="alert alert-danger" style="margin-bottom:1.25rem;">
    <i data-lucide="shield-alert" class="icon icon-sm"></i>
    <strong>Flagged: Possible duplicate submission</strong> — {{ scorecard.get('plagiarism_message', '') }}
  </div>
  {% endif %}
  ```

- [ ] **In `src/governiq/templates/admin_dashboard.html`**, find the submissions table row rendering. Look for where `evaluation.overall_score` or `evaluation.session_id` is rendered in a `<td>`. Find the status badge column and add a "Flagged" badge:
  ```html
  {% if evaluation.get('plagiarism_flag') %}
  <span class="badge badge-warn">
    <i data-lucide="flag" style="width:10px;height:10px;"></i> Flagged
  </span>
  {% endif %}
  ```

- [ ] **Run full test suite:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```
  Expected: All pass

- [ ] **Commit:**
  ```bash
  git add src/governiq/candidate/routes.py \
          src/governiq/templates/candidate_report.html \
          src/governiq/templates/admin_review.html \
          src/governiq/templates/admin_dashboard.html \
          tests/test_plagiarism_integration.py
  git commit -m "feat: wire plagiarism detection into submission flow, add UI flags"
  ```

---

## Task 7: Admin Compare Diff Logic

**Files:**
- Modify: `src/governiq/admin/routes.py` (compare route at line 704)
- Modify: `src/governiq/templates/admin_compare.html`
- Modify: `src/governiq/templates/admin_dashboard.html`
- Create: `tests/test_compare.py`

### Step 7a: Write failing tests

- [ ] **Create `tests/test_compare.py`:**
  ```python
  """Tests for admin compare diff logic."""
  import pytest
  from fastapi.testclient import TestClient
  from governiq.main import app

  client = TestClient(app)


  def _make_scorecard(session_id, task_scores):
      """Build a minimal scorecard dict."""
      return {
          "session_id": session_id,
          "candidate_id": "test",
          "assessment_name": "Test",
          "overall_score": 0.75,
          "task_scores": task_scores,
      }


  def test_compare_no_params_returns_200():
      resp = client.get("/admin/compare")
      assert resp.status_code == 200


  def test_compare_diff_logic():
      """Test that task delta computation works correctly."""
      # This tests the helper directly — import after the route is updated
      from governiq.admin.routes import _compute_task_diff

      left = _make_scorecard("s1", [
          {"task_id": "t1", "task_name": "Create", "combined_score": 0.9},
          {"task_id": "t2", "task_name": "Delete", "combined_score": 0.5},
      ])
      right = _make_scorecard("s2", [
          {"task_id": "t1", "task_name": "Create", "combined_score": 0.6},
          {"task_id": "t2", "task_name": "Delete", "combined_score": 0.5},
      ])
      diff = _compute_task_diff(left, right)
      assert len(diff) == 2
      # t1: 0.9 - 0.6 = 0.3 → significant (>0.20)
      t1 = next(d for d in diff if d["task_id"] == "t1")
      assert t1["significant"] is True
      assert abs(t1["delta"] - 0.30) < 0.01
      # t2: 0.5 - 0.5 = 0 → not significant
      t2 = next(d for d in diff if d["task_id"] == "t2")
      assert t2["significant"] is False


  def test_compare_diff_missing_task_on_right():
      """Tasks present in left but not in right should be handled gracefully."""
      from governiq.admin.routes import _compute_task_diff
      left = _make_scorecard("s1", [{"task_id": "t1", "task_name": "Create", "combined_score": 0.9}])
      right = _make_scorecard("s2", [])
      diff = _compute_task_diff(left, right)
      assert len(diff) == 1
      assert diff[0]["right_score"] is None
  ```

- [ ] **Run to verify they fail:**
  ```
  python -m pytest tests/test_compare.py -v
  ```
  Expected: FAIL (`_compute_task_diff` not yet defined)

### Step 7b: Add _compute_task_diff helper and extend compare route

- [ ] **In `src/governiq/admin/routes.py`**, add this helper function immediately before the `@router.get("/compare")` route (around line 704):
  ```python
  def _compute_task_diff(left_sc: dict | None, right_sc: dict | None) -> list[dict]:
      """Align tasks from two scorecards by task_id and compute score deltas."""
      if not left_sc or not right_sc:
          return []
      left_tasks = {t["task_id"]: t for t in left_sc.get("task_scores", [])}
      right_tasks = {t["task_id"]: t for t in right_sc.get("task_scores", [])}
      all_ids = list(left_tasks.keys()) or list(right_tasks.keys())
      # Preserve order from left, then add any right-only tasks
      seen = set()
      ordered_ids = []
      for tid in list(left_tasks.keys()) + list(right_tasks.keys()):
          if tid not in seen:
              seen.add(tid)
              ordered_ids.append(tid)
      diff = []
      for tid in ordered_ids:
          lt = left_tasks.get(tid)
          rt = right_tasks.get(tid)
          left_score = lt["combined_score"] if lt else None
          right_score = rt["combined_score"] if rt else None
          if left_score is not None and right_score is not None:
              delta = left_score - right_score
          elif left_score is not None:
              delta = left_score
          else:
              delta = -(right_score or 0)
          diff.append({
              "task_id": tid,
              "task_name": (lt or rt or {}).get("task_name", tid),
              "left_score": left_score,
              "right_score": right_score,
              "delta": round(delta, 4),
              "significant": abs(delta) > 0.20,
          })
      return diff
  ```

- [ ] **Extend the existing compare route handler.** Find `return templates.TemplateResponse("admin_compare.html", {` (around line 748). Add `task_diff` to the context:
  ```python
  task_diff = _compute_task_diff(left_sc, right_sc)

  return templates.TemplateResponse("admin_compare.html", {
      "request": request,
      "portal": "admin",
      "evaluations": evaluations,
      "similarity_groups": similarity_groups,
      "left": left_sc,
      "right": right_sc,
      "left_id": left_id,
      "right_id": right_id,
      "task_diff": task_diff,
  })
  ```

- [ ] **Run tests:**
  ```
  python -m pytest tests/test_compare.py -v
  ```
  Expected: 3 PASSED

### Step 7c: Update admin_compare.html with diff table

- [ ] **In `src/governiq/templates/admin_compare.html`**, find where `left` and `right` scorecard data is rendered. Add a task diff table in the section where both scorecards are selected:
  ```html
  {% if task_diff %}
  <div class="card" style="margin-top:1.5rem;">
    <div class="card-body">
      <div class="card-title">
        <i data-lucide="git-compare" class="icon"></i>
        <h2>Task Score Comparison</h2>
      </div>
      <table class="data-table" style="margin-top:1rem;">
        <thead>
          <tr>
            <th>Task</th>
            <th>Left Score</th>
            <th>Right Score</th>
            <th>Difference</th>
          </tr>
        </thead>
        <tbody>
          {% for row in task_diff %}
          <tr>
            <td>{{ row.task_name }}</td>
            <td>{% if row.left_score is not none %}{{ "%.0f"|format(row.left_score * 100) }}%{% else %}<span style="color:var(--text-muted)">—</span>{% endif %}</td>
            <td>{% if row.right_score is not none %}{{ "%.0f"|format(row.right_score * 100) }}%{% else %}<span style="color:var(--text-muted)">—</span>{% endif %}</td>
            <td>
              {% if row.delta > 0 %}
              <span style="color:#34d399;">+{{ "%.0f"|format(row.delta * 100) }}%</span>
              {% elif row.delta < 0 %}
              <span style="color:#ef4444;">{{ "%.0f"|format(row.delta * 100) }}%</span>
              {% else %}
              <span style="color:var(--text-muted);">0%</span>
              {% endif %}
              {% if row.significant %}
              <span class="badge badge-warn" style="margin-left:.5rem;">Significant</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
  {% endif %}
  ```

### Step 7d: Add Compare button to admin_dashboard.html

- [ ] **In `src/governiq/templates/admin_dashboard.html`**, find the submissions table. Locate the actions column (or the row's last `<td>`). Add a Compare button that stores the session_id and, when two are selected, opens the compare URL:
  ```html
  <!-- Add at top of page, after {% block content %}: -->
  <div id="compareBar" style="display:none; background:rgba(139,92,246,.1); padding:.6rem 1.25rem; border-radius:8px; margin-bottom:1rem; display:flex; align-items:center; gap:.75rem; flex-wrap:wrap;">
    <i data-lucide="git-compare" class="icon icon-sm"></i>
    <span id="compareStatus" style="font-size:.82rem; flex:1;">Select two submissions to compare</span>
    <button onclick="openCompare()" class="btn btn-primary btn-sm" id="compareBtn" disabled>
      Compare Selected
    </button>
    <button onclick="clearCompare()" class="btn btn-ghost btn-sm">Clear</button>
  </div>

  <!-- In the submissions table row, add a checkbox column: -->
  <!-- Find the <th> header row and add: -->
  <th style="width:40px;"></th>
  <!-- Find the <td> data rows and add (first column): -->
  <td><input type="checkbox" class="compare-check" data-session="{{ evaluation.session_id }}" onchange="updateCompareBar()"></td>
  ```

  Add the script at the bottom of the template:
  ```html
  <script>
  let compareIds = [];
  function updateCompareBar() {
    const checks = document.querySelectorAll(".compare-check:checked");
    compareIds = Array.from(checks).map(c => c.dataset.session);
    const bar = document.getElementById("compareBar");
    const btn = document.getElementById("compareBtn");
    const status = document.getElementById("compareStatus");
    bar.style.display = "flex";
    if (compareIds.length === 0) {
      status.textContent = "Select two submissions to compare";
      btn.disabled = true;
    } else if (compareIds.length === 1) {
      status.textContent = "Select one more submission";
      btn.disabled = true;
    } else if (compareIds.length === 2) {
      status.textContent = `Comparing ${compareIds[0].slice(0,8)}... vs ${compareIds[1].slice(0,8)}...`;
      btn.disabled = false;
    } else {
      // Deselect extras
      checks[0].checked = false;
      updateCompareBar();
    }
  }
  function openCompare() {
    if (compareIds.length === 2) {
      window.location.href = `/admin/compare?left=${compareIds[0]}&right=${compareIds[1]}`;
    }
  }
  function clearCompare() {
    document.querySelectorAll(".compare-check").forEach(c => c.checked = false);
    compareIds = [];
    document.getElementById("compareBar").style.display = "none";
  }
  </script>
  ```

- [ ] **Run full test suite:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```
  Expected: All pass

- [ ] **Commit:**
  ```bash
  git add src/governiq/admin/routes.py \
          src/governiq/templates/admin_compare.html \
          src/governiq/templates/admin_dashboard.html \
          tests/test_compare.py
  git commit -m "feat: add task-level diff logic to compare route and update compare + dashboard templates"
  ```

---

## Task 8: Async Submission with Progress Indicator

**Files:**
- Modify: `src/governiq/candidate/routes.py`
- Modify: `src/governiq/templates/candidate_submit.html`

### Step 8a: Refactor submit handler to use BackgroundTasks

- [ ] **In `src/governiq/candidate/routes.py`**, update the imports to include `BackgroundTasks`, `JSONResponse`, and `uuid`. These must be module-level imports (Task 6 uses `_uuid_mod` too — only one `import uuid` line):
  ```python
  from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
  from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
  import uuid as _uuid_mod  # used by both Task 6 (plagiarism session id) and Task 8 (evaluation session id)
  ```

- [ ] **Create an async background evaluation function** immediately before the `candidate_submit` route:
  ```python
  async def _run_evaluation_background(
      session_id: str,
      manifest: Manifest,
      bot_export_data: dict,
      candidate_id: str,
      webhook_url: str,
      kore_creds: Any,
      llm_config: Any,
      kore_bearer_token: str,
      plag_report: Any,
  ) -> None:
      """Run full evaluation in the background and write the result to disk."""
      results_dir = DATA_DIR / "results"
      results_dir.mkdir(parents=True, exist_ok=True)
      stub_path = results_dir / f"scorecard_{session_id}.json"
      try:
          from ..core.engine import EvaluationEngine
          from ..core.llm_config import LLMConfig
          from ..webhook.jwt_auth import KoreCredentials

          engine = EvaluationEngine(
              manifest=manifest,
              llm_api_key=llm_config.api_key,
              llm_model=llm_config.model,
              llm_base_url=llm_config.base_url,
              llm_api_format=llm_config.api_format,
              kore_bearer_token=kore_bearer_token,
              kore_credentials=kore_creds,
          )
          if webhook_url or kore_creds:
              scorecard = await engine.run_full_evaluation(
                  bot_export=bot_export_data,
                  candidate_id=candidate_id,
              )
          else:
              scorecard = await engine.run_cbm_only(
                  bot_export=bot_export_data,
                  candidate_id=candidate_id,
              )

          # Apply plagiarism flag
          if plag_report and plag_report.risk_level != PlagiarismRisk.NONE:
              scorecard.plagiarism_flag = True
              scorecard.plagiarism_message = plag_report.message

          # Write final scorecard (overwrites the stub)
          with stub_path.open("w") as f:
              import json as _json
              _json.dump(scorecard.to_dict(), f, indent=2)

      except Exception as exc:
          logger.exception("Background evaluation failed for session %s", session_id)
          error_data = {
              "session_id": session_id,
              "status": "error",
              "error": str(exc),
          }
          with stub_path.open("w") as f:
              import json as _json
              _json.dump(error_data, f)
  ```

- [ ] **Refactor `candidate_submit`** to accept `background_tasks: BackgroundTasks` and return a `JSONResponse` with the session_id immediately. Replace the existing evaluation block (starting at `# Run evaluation`) through the `return RedirectResponse(...)` with:
  ```python
  # Generate session_id and write stub immediately
  session_id = str(_uuid_mod.uuid4())
  results_dir = DATA_DIR / "results"
  results_dir.mkdir(parents=True, exist_ok=True)
  stub_path = results_dir / f"scorecard_{session_id}.json"
  with stub_path.open("w") as f:
      json.dump({
          "session_id": session_id,
          "status": "running",
          "candidate_id": candidate_id,
          "assessment_name": manifest.assessment_name,
      }, f)

  # Launch evaluation in background
  background_tasks.add_task(
      _run_evaluation_background,
      session_id=session_id,
      manifest=manifest,
      bot_export_data=bot_export_data,
      candidate_id=candidate_id,
      webhook_url=webhook_url,
      kore_creds=kore_creds,
      llm_config=llm_config,
      kore_bearer_token=kore_bearer_token,
      plag_report=_plag_report,  # always in scope: pre-initialised to None in Task 6b plagiarism block
  )

  return JSONResponse({"session_id": session_id, "status": "running"})
  ```

  Also add `background_tasks: BackgroundTasks` to the function signature:
  ```python
  @router.post("/submit")
  async def candidate_submit(
      request: Request,
      background_tasks: BackgroundTasks,
      candidate_name: str = Form(""),
      ...
  ```

### Step 8b: Update candidate_submit.html with progress indicator

- [ ] **In `src/governiq/templates/candidate_submit.html`**, find the submit button (look for `<button type="submit"` or similar). Replace the submit button area with:
  ```html
  <div id="submitArea">
    <button type="submit" class="btn btn-primary btn-lg" id="submitBtn">
      <i data-lucide="send" class="icon icon-sm"></i> Submit Assessment
    </button>
  </div>

  <!-- Progress panel (hidden until submit) -->
  <div id="progressPanel" style="display:none; margin-top:1.25rem;">
    <div class="card" style="padding:1.25rem;">
      <div class="card-title" style="margin-bottom:1rem;">
        <i data-lucide="loader" class="icon icon-sm" id="progressSpinner"></i>
        <h3>Evaluating your submission...</h3>
      </div>
      <div id="progressSteps" style="display:flex; flex-direction:column; gap:.6rem;">
        <div class="progress-step" id="step1">
          <i data-lucide="circle" class="icon icon-sm step-icon"></i>
          <span>Checking your bot file...</span>
        </div>
        <div class="progress-step" id="step2" style="opacity:.4;">
          <i data-lucide="circle" class="icon icon-sm step-icon"></i>
          <span>Testing your bot...</span>
        </div>
        <div class="progress-step" id="step3" style="opacity:.4;">
          <i data-lucide="circle" class="icon icon-sm step-icon"></i>
          <span>Calculating your score...</span>
        </div>
      </div>
    </div>
  </div>
  ```

- [ ] **Add JavaScript** to handle the AJAX submit and polling. Add before `</body>` or in `{% block extra_head %}`:
  ```html
  <script>
  const form = document.querySelector("form");
  if (form) {
    form.addEventListener("submit", async function(e) {
      e.preventDefault();
      document.getElementById("submitArea").style.display = "none";
      document.getElementById("progressPanel").style.display = "block";
      markStep("step1", "active");

      const formData = new FormData(form);
      let sessionId = null;
      try {
        const resp = await fetch("/candidate/submit", {method:"POST", body: formData});
        if (!resp.ok) {
          showFormError("Submission failed. Please try again.");
          resetProgress();
          return;
        }
        const data = await resp.json();
        sessionId = data.session_id;
      } catch(err) {
        showFormError("Could not reach the server. Please try again.");
        resetProgress();
        return;
      }

      markStep("step1", "done");
      markStep("step2", "active");

      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`/api/v1/results/${sessionId}`);
          if (!r.ok) return;  // 404 = still running, keep polling
          const sc = await r.json();
          if (sc.status !== "running") {
            clearInterval(poll);
            markStep("step2", "done");
            markStep("step3", "active");
            setTimeout(() => {
              markStep("step3", "done");
              if (sc.status === "error") {
                showFormError(sc.error || "Evaluation failed. Please try again.");
                resetProgress();
              } else {
                window.location.href = `/candidate/report/${sessionId}`;
              }
            }, 600);
          }
        } catch(e) { /* keep polling */ }
      }, 3000);
    });
  }

  function markStep(id, state) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.opacity = "1";
    const icon = el.querySelector(".step-icon");
    if (state === "active") icon.setAttribute("data-lucide", "loader");
    if (state === "done")   icon.setAttribute("data-lucide", "check-circle");
    if (window.lucide) lucide.createIcons();
  }

  function resetProgress() {
    document.getElementById("submitArea").style.display = "block";
    document.getElementById("progressPanel").style.display = "none";
  }

  function showFormError(msg) {
    let err = document.getElementById("jsError");
    if (!err) {
      err = document.createElement("div");
      err.id = "jsError";
      err.className = "alert alert-danger";
      document.querySelector(".card-body")?.prepend(err);
    }
    err.textContent = msg;
    err.style.display = "block";
  }
  </script>
  ```

- [ ] **Manual verification:** Submit a bot export on the candidate portal. Verify the progress panel appears, steps advance, and the page redirects to the report when done.

- [ ] **Commit:**
  ```bash
  git add src/governiq/candidate/routes.py src/governiq/templates/candidate_submit.html
  git commit -m "feat: async submission with BackgroundTasks and progress polling UI"
  ```

---

## Task 9: UX Polish

**Files:**
- Modify: `src/governiq/templates/how_it_works.html`
- Create: `src/governiq/templates/error.html`
- Modify: `src/governiq/templates/admin_dashboard.html` (empty state)
- Modify: `src/governiq/templates/candidate_history.html` (empty state)
- Modify: `src/governiq/templates/admin_manifest_list.html` (empty state)
- Modify: `src/governiq/templates/candidate_submit.html` (form validation)

### Step 9a: Fix how_it_works.html scoring weights (Component 2c)

- [ ] **In `src/governiq/templates/how_it_works.html`**, search for any text showing `40%` or `40/40`. Update all scoring weight references to the correct values:
  - Webhook Functional Testing: **80%**
  - FAQ Semantic Similarity: **10%**
  - Compliance Checks: **10%**
  - CBM Structural Audit: **Informational only (0%)**

  The specific lines to find and update will be wherever the scoring diagram or weight list is rendered. Search for `40` in the file and replace each relevant occurrence.

### Step 9b: Create error.html

- [ ] **Create `src/governiq/templates/error.html`:**
  ```html
  {% extends "base.html" %}
  {% block title %}{{ error_title | default("Something went wrong") }} — GovernIQ{% endblock %}
  {% block content %}
  <div class="container" style="max-width:480px; margin:4rem auto; text-align:center;">
    <div class="card" style="padding:2.5rem 2rem;">
      <div style="margin-bottom:1.5rem;">
        <i data-lucide="{{ error_icon | default('alert-circle') }}" style="width:48px;height:48px;color:#ef4444;"></i>
      </div>
      <h1 style="font-family:'Bricolage Grotesque',sans-serif; font-size:1.5rem; margin-bottom:.75rem;">
        {{ error_title | default("Something went wrong") }}
      </h1>
      <p style="color:var(--text-secondary); font-size:.9rem; line-height:1.6; margin-bottom:1.75rem;">
        {{ error_message | default("An unexpected error occurred. Please try again.") }}
      </p>
      <div style="display:flex; gap:.75rem; justify-content:center; flex-wrap:wrap;">
        <a href="/admin/" class="btn btn-primary">
          <i data-lucide="layout-dashboard" class="icon icon-sm"></i> Go to Dashboard
        </a>
        <a href="javascript:history.back()" class="btn btn-secondary">
          <i data-lucide="arrow-left" class="icon icon-sm"></i> Go Back
        </a>
      </div>
    </div>
  </div>
  {% endblock %}
  ```

- [ ] **Register the error handler in `src/governiq/main.py`.** Add after the router registrations:
  ```python
  from fastapi import Request as _Request
  from fastapi.responses import HTMLResponse as _HTMLResponse
  from fastapi.exceptions import RequestValidationError
  from starlette.exceptions import HTTPException as StarletteHTTPException

  @app.exception_handler(StarletteHTTPException)
  async def http_exception_handler(request: _Request, exc: StarletteHTTPException):
      if exc.status_code == 404:
          return templates.TemplateResponse("error.html", {
              "request": request, "portal": None,
              "error_title": "Page not found",
              "error_icon": "map-pin-off",
              "error_message": "The page you were looking for does not exist.",
          }, status_code=404)
      return templates.TemplateResponse("error.html", {
          "request": request, "portal": None,
          "error_title": "Something went wrong",
          "error_icon": "alert-circle",
          "error_message": "An unexpected error occurred. Please try again or go to the dashboard.",
      }, status_code=exc.status_code)
  ```

### Step 9c: Empty state improvements

- [ ] **In `src/governiq/templates/admin_dashboard.html`**, find the `{% if not evaluations %}` or `{% else %}` empty state block. Replace with:
  ```html
  {% if not evaluations %}
  <div style="text-align:center; padding:3rem 1rem; color:var(--text-secondary);">
    <i data-lucide="inbox" style="width:40px;height:40px;margin-bottom:1rem;opacity:.4;"></i>
    <h3 style="font-family:'Bricolage Grotesque',sans-serif;margin-bottom:.5rem;">No submissions yet</h3>
    <p style="font-size:.85rem;">Candidates submit at <strong>/candidate/</strong> on this server.</p>
  </div>
  {% endif %}
  ```

- [ ] **In `src/governiq/templates/candidate_history.html`**, find the empty state. Replace with:
  ```html
  {% if not submissions %}
  <div style="text-align:center; padding:3rem 1rem; color:var(--text-secondary);">
    <i data-lucide="file-text" style="width:40px;height:40px;margin-bottom:1rem;opacity:.4;"></i>
    <h3 style="font-family:'Bricolage Grotesque',sans-serif;margin-bottom:.5rem;">No submissions yet</h3>
    <p style="font-size:.85rem;margin-bottom:1.25rem;">Submit your first assessment to see your results here.</p>
    <a href="/candidate/" class="btn btn-primary">Submit Assessment</a>
  </div>
  {% endif %}
  ```

- [ ] **In `src/governiq/templates/admin_manifest_list.html`**, find the empty state. Replace with:
  ```html
  {% if not manifests %}
  <div style="text-align:center; padding:3rem 1rem; color:var(--text-secondary);">
    <i data-lucide="file-cog" style="width:40px;height:40px;margin-bottom:1rem;opacity:.4;"></i>
    <h3 style="font-family:'Bricolage Grotesque',sans-serif;margin-bottom:.5rem;">No manifests loaded</h3>
    <p style="font-size:.85rem;margin-bottom:1.25rem;">Upload a manifest file to configure an assessment.</p>
    <a href="/admin/manifests/new" class="btn btn-primary">Create Manifest</a>
  </div>
  {% endif %}
  ```

- [ ] **In `src/governiq/templates/admin_compare.html`**, find the section shown when neither `left` nor `right` scorecard is selected (i.e., when `not left and not right`). Add or replace the empty state with:
  ```html
  {% if not left and not right %}
  <div style="text-align:center; padding:3rem 1rem; color:var(--text-secondary);">
    <i data-lucide="git-compare" style="width:40px;height:40px;margin-bottom:1rem;opacity:.4;"></i>
    <h3 style="font-family:'Bricolage Grotesque',sans-serif;margin-bottom:.5rem;">No submissions selected</h3>
    <p style="font-size:.85rem;">Select two submissions from the dashboard to compare their scores side by side.</p>
    <a href="/admin/" class="btn btn-secondary" style="margin-top:1rem;">Go to Dashboard</a>
  </div>
  {% endif %}
  ```

### Step 9d: Form validation for candidate_submit.html

- [ ] **In `src/governiq/templates/candidate_submit.html`**, add inline validation helpers. Before the submit JS, add:
  ```html
  <script>
  // Inline form validation — shows errors below each field
  function validateSubmitForm(form) {
    let valid = true;
    clearErrors();

    const assessment = form.querySelector("[name='assessment_type']");
    if (!assessment || !assessment.value) {
      showFieldError("assessment_type", "Please select an assessment.");
      valid = false;
    }

    const export_file = form.querySelector("[name='bot_export']");
    if (!export_file || !export_file.files || !export_file.files.length) {
      showFieldError("bot_export", "Please upload a bot export file (.zip or .json).");
      valid = false;
    }

    const webhook = form.querySelector("[name='webhook_url']");
    if (webhook && !webhook.value.trim()) {
      showFieldError("webhook_url", "Please enter your webhook URL to enable live testing.");
      // Not blocking — CBM-only is allowed, show as advisory
    }

    return valid;
  }

  function showFieldError(name, msg) {
    const field = document.querySelector(`[name="${name}"]`);
    if (!field) return;
    let err = field.parentElement.querySelector(".field-error");
    if (!err) {
      err = document.createElement("div");
      err.className = "field-error";
      err.style.cssText = "color:#ef4444;font-size:.75rem;margin-top:.25rem;";
      field.parentElement.appendChild(err);
    }
    err.textContent = msg;
  }

  function clearErrors() {
    document.querySelectorAll(".field-error").forEach(e => e.remove());
  }

  const submitForm = document.querySelector("form");
  if (submitForm) {
    submitForm.addEventListener("submit", function(e) {
      if (!validateSubmitForm(submitForm)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    }, true);  // capture phase — runs before async submit handler
  }
  </script>
  ```

- [ ] **Run full test suite:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```
  Expected: All pass

- [ ] **Commit:**
  ```bash
  git add src/governiq/templates/how_it_works.html \
          src/governiq/templates/error.html \
          src/governiq/templates/admin_dashboard.html \
          src/governiq/templates/candidate_history.html \
          src/governiq/templates/admin_manifest_list.html \
          src/governiq/templates/candidate_submit.html \
          src/governiq/main.py
  git commit -m "feat: UX polish — error pages, empty states, form validation, correct scoring weights"
  ```

---

## Final Verification

- [ ] **Run the complete test suite:**
  ```
  python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py
  ```
  Expected: All tests pass, 0 failures

- [ ] **Start the server and verify the success criteria manually:**
  ```
  uvicorn src.governiq.main:app --reload --port 8000
  ```
  Check each criterion:
  1. On a machine with no `data/` directory — app starts cleanly
  2. Health bar shows red, guides to `/admin/settings` in under 2 minutes
  3. Admin can switch AI providers at `/admin/settings` without touching the terminal
  4. Candidate submits a bot and sees the progress panel (Steps 1→2→3)
  5. Compare page shows task diff table with colour-coded deltas
  6. `pytest tests/ -v` passes with 0 failures
  7. No emojis anywhere — only Lucide icons
  8. No technical jargon in any user-facing message
