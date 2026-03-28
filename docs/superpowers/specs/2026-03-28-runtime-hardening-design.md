# Evaluation Runtime Hardening — Design Spec

**Date:** 2026-03-28
**Sprint:** Runtime Hardening (Sprint 2A)
**Status:** Approved — ready for implementation

---

## What this sprint builds

Eight targeted improvements that make the evaluation engine production-safe. No new patterns, no UI overhaul. Every decision in this spec was confirmed in a product architecture session on 2026-03-28.

**What is NOT in this sprint:**
- Plan 2 (Web Driver): Playwright + Kore.ai Web SDK — separate sprint
- Plan 3 (Platform Assumption Workbench) — separate sprint

---

## Architecture Overview

The engine gains a concurrency guard, a full timeout hierarchy, and per-turn debug log verification. The conversation driver becomes deterministic (temperature 0). All external API calls get automatic retry. The submission form becomes strict about credentials and supports per-task mock API URLs.

```
Submission form
  → credentials (mandatory) + per-task mock API URLs
  → EvalConcurrencyGuard (one evaluation per bot at a time)
  → Gate 0 (manifest-aware: WEB_DRIVER tasks = web channel FAIL, not WARN)
  → EvaluationEngine (30-min total timeout)
    → per-task (3-min timeout)
      → LLM driver (temperature=0, 30s per-turn timeout)
        → webhook send
        → DebugLogVerifier.verify_turn() (poll 1s × 10, then fallback)
          primary: Kore debug log (real-time, per-turn)
          fallback: mock API GET verification
      → KoreAPIClient._api_* (all calls via retry_with_backoff)
```

---

## Decision Log

### 1. LLM Temperature = 0

**Why:** LLM temperature 0.3 (current) produces non-deterministic turn choices. Two identical bots can score differently depending on which random branch the LLM picks. Temperature 0 makes evaluation reproducible.

**Change:** `LLMConversationDriver.__init__` temperature default: `0.3 → 0.0`

---

### 2. Retry with Exponential Backoff

**Why:** `retry.py` exists but none of the `kore_api.py` methods use it. Transient errors (502, 503, 504, connect errors) currently cause hard failures. This is especially bad for the debug log polling path where a single transient error kills the verification.

**Change:** All `KoreAPIClient._api_get` / `_api_post` / `_api_get_kore` / `_api_post_kore` calls are wrapped in `retry_with_backoff(max_retries=3, base_delay=2.0)`.

---

### 3. Admin Credentials Mandatory

**Why:** Without `client_id` + `client_secret`, Gate 0 silently SKIPs bot_credentials, bot_published, and web_channel checks. We cannot verify publish status or whether web channel is enabled. Debug log verification also requires the admin JWT.

**Change:** In `candidate/routes.py`, `client_id` and `client_secret` become required form fields. Gate 0 always has a `KoreAPIClient`. The form shows a clear error if credentials are absent.

---

### 4. Gate 0 — Manifest-Aware Web Channel Severity

**Why:** Currently, a missing web channel is always WARN. But if the manifest has `WEB_DRIVER` tasks, evaluation cannot score those tasks without a web channel — so WARN is wrong, it should be FAIL.

**Change:** `Gate0Checker` accepts `has_web_driver_tasks: bool`. `_check_web_channel` returns FAIL (not WARN) when `has_web_driver_tasks=True`. Engine passes `any(t.ui_policy == UIPolicy.WEB_DRIVER for t in manifest.tasks)`.

---

### 5. Per-Task Mock API URL

**Why:** Currently the manifest has one global `mock_api_base_url`. A candidate may use different mock APIs for different tasks (e.g. flight booking API vs hotel booking API). A single URL cannot cover both.

**Architecture decision:** The manifest schema knows per-task which API resource is needed. The candidate provides which URL serves each resource. These are married at submission time.

**Change:**
- `TaskDefinition` gains `mock_api_url: str = ""` (overrides global when set)
- Submission form shows a URL input per task that has a `state_assertion` (dynamic, driven by selected manifest)
- `candidate/routes.py` reads `task_{task_id}_mock_url` form fields and writes them into the manifest's task definitions before passing to the engine
- Engine: when building verify URL, uses `task.mock_api_url or self.manifest.mock_api_base_url`

---

### 6. Per-Bot Concurrency Guard

**Why:** Multiple submissions for the same bot simultaneously would interleave debug log queries (the debug log API is keyed by session ID, but two concurrent evaluations of the same bot share the same JWT and the bot itself has bounded thread capacity). Risk of cross-contamination.

**Decision:** Max 1 evaluation running per bot at a time. Queued submissions wait (they are not rejected).

**Change:** New `src/governiq/core/concurrency.py` — `EvalConcurrencyGuard` with a `dict[str, asyncio.Lock]`. Engine acquisition wrapper. The evaluation background task acquires the lock for `bot_id` before calling `run_full_evaluation`, releases on completion or exception.

---

### 7. Timeout Hierarchy

**Why:** Without timeouts, one unresponsive bot blocks the queue indefinitely.

**Decision (confirmed in architecture session):**
- Per-turn hard limit: **30s** — on breach, mark turn failed, log reason, continue to next turn
- Per-task limit: **3 minutes** — on breach, task scored 0, log reason, continue to next task
- Total evaluation limit: **30 minutes** — on breach, partial results saved, status = `timeout`, flagged for manual review

**Change:**
- `LLMConversationDriver.run_task()` wraps each turn in `asyncio.wait_for(..., timeout=30.0)`
- `EvaluationEngine.run_full_evaluation()` wraps each task in `asyncio.wait_for(..., timeout=180.0)`
- `EvaluationEngine.run_full_evaluation()` wraps entire evaluation in `asyncio.wait_for(..., timeout=1800.0)`, catches `TimeoutError`, saves partial scorecard with status = `timeout`

---

### 8. Debug Log Verification — Per-Turn, Real-Time

**Why:** The current verification model is mock API only. That tells us whether the bot saved the record, but not *why* the bot took an action. Debug logs give real-time insight into intent detection, service node execution, and entity extraction — enabling much richer failure analysis.

**Decision (confirmed):**
- Per-turn, real-time: after each webhook response, poll debug log for this session
- Poll every 1s, timeout after 10s, then fallback to mock API verification
- If debug log confirms the expected intent/service call → mark turn verified via debug log
- If debug log times out → fall back to mock API GET (existing path)
- 25s worst case per turn is acceptable

**Architecture:**
- New module: `src/governiq/webhook/debug_log_verifier.py`
  - `DebugLogVerifier(kore_api_client, poll_interval=1.0, poll_timeout=10.0)`
  - `async verify_turn(session_id, expected_intent=None, expected_service_call=None) -> DebugLogResult`
  - `DebugLogResult(dataclass)`: `verified: bool`, `source: Literal["debug_log", "mock_api", "timeout"]`, `raw_entries: list[dict]`, `matched_intent: str | None`, `matched_service: str | None`
- `LLMConversationDriver` receives `DebugLogVerifier | None`; calls `verify_turn()` after each turn

---

## File Map

| File | Action | Purpose |
|------|---------|---------|
| `src/governiq/webhook/driver.py` | Modify | temperature=0 default; 30s per-turn timeout; accept DebugLogVerifier |
| `src/governiq/webhook/kore_api.py` | Modify | Wrap all `_api_*` calls with `retry_with_backoff` |
| `src/governiq/webhook/debug_log_verifier.py` | **Create** | Per-turn debug log polling with mock API fallback |
| `src/governiq/core/concurrency.py` | **Create** | Per-bot asyncio.Lock concurrency guard |
| `src/governiq/core/gate0.py` | Modify | `has_web_driver_tasks` param; web channel FAIL severity |
| `src/governiq/core/manifest.py` | Modify | `TaskDefinition.mock_api_url: str = ""` |
| `src/governiq/core/engine.py` | Modify | Pass `has_web_driver_tasks` to Gate0; use per-task mock_api_url; timeout wrappers; build DebugLogVerifier |
| `src/governiq/candidate/routes.py` | Modify | Credentials required; read per-task mock URL form fields |
| `src/governiq/templates/candidate_submit.html` | Modify | Mark credentials required; per-task mock API URL inputs |
| `tests/test_debug_log_verifier.py` | **Create** | DebugLogVerifier unit tests |
| `tests/test_concurrency_guard.py` | **Create** | EvalConcurrencyGuard unit tests |
| `tests/test_gate0_web_driver_severity.py` | **Create** | FAIL vs WARN based on `has_web_driver_tasks` |
| `tests/test_engine_timeouts.py` | **Create** | Per-turn / per-task / total timeout behavior |
| `tests/test_kore_api_retry.py` | **Create** | Retry wiring on transient errors |

---

## Non-Goals

- No Playwright, no Web SDK — that is Plan 2
- No frontend redesign — templates get minimal targeted changes only
- No new engine patterns
- No scoring weight changes
