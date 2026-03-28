# Evaluation Runtime Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the evaluation runtime with deterministic LLM, per-turn debug log verification, timeout hierarchy, per-bot concurrency control, per-task mock API URLs, mandatory credentials, and automatic retry — making the engine production-safe.

**Architecture:** A new `DebugLogVerifier` polls Kore debug logs per turn with mock API fallback. A new `EvalConcurrencyGuard` enforces one evaluation per bot at a time. The engine gains a three-tier timeout hierarchy. All external API calls go through the existing `retry_with_backoff` utility. See spec: `docs/superpowers/specs/2026-03-28-runtime-hardening-design.md`

**Tech Stack:** Python 3.14, FastAPI, asyncio, httpx, pytest, Pydantic v2

---

## File Map

| File | Action |
|------|--------|
| `src/governiq/webhook/driver.py` | Modify — temperature=0, per-turn timeout, DebugLogVerifier integration |
| `src/governiq/webhook/kore_api.py` | Modify — wrap all `_api_*` with `retry_with_backoff` |
| `src/governiq/webhook/debug_log_verifier.py` | **Create** — per-turn debug log polling + mock fallback |
| `src/governiq/core/concurrency.py` | **Create** — per-bot asyncio.Lock guard |
| `src/governiq/core/gate0.py` | Modify — `has_web_driver_tasks` → FAIL severity for web channel |
| `src/governiq/core/manifest.py` | Modify — `TaskDefinition.mock_api_url: str = ""` |
| `src/governiq/core/engine.py` | Modify — timeout wrappers, Gate0 has_web_driver_tasks, per-task URL, DebugLogVerifier |
| `src/governiq/candidate/routes.py` | Modify — credentials required, per-task mock URLs |
| `src/governiq/templates/candidate_submit.html` | Modify — mark credentials required, per-task URL fields |

---

## Task 1: LLM Temperature = 0

**Files:**
- Modify: `src/governiq/webhook/driver.py`
- Test: `tests/test_llm_driver_temperature.py`

**Context:** `LLMConversationDriver.__init__` currently defaults temperature to `0.3`. This makes evaluation non-deterministic. Change the default to `0.0` and add a test that confirms the default.

- [ ] **Step 1.1: Write the failing test**

```python
# tests/test_llm_driver_temperature.py
from governiq.webhook.driver import LLMConversationDriver


def test_default_temperature_is_zero():
    driver = LLMConversationDriver(api_key="test")
    assert driver.temperature == 0.0


def test_temperature_can_be_overridden():
    driver = LLMConversationDriver(api_key="test", temperature=0.7)
    assert driver.temperature == 0.7
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
python -m pytest tests/test_llm_driver_temperature.py -v
```

Expected: `FAIL — AssertionError: assert 0.3 == 0.0`

- [ ] **Step 1.3: Change default temperature in driver.py**

In `src/governiq/webhook/driver.py`, line `temperature: float = 0.3`:

```python
# Change from:
temperature: float = 0.3,
# Change to:
temperature: float = 0.0,
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
python -m pytest tests/test_llm_driver_temperature.py -v
```

Expected: 2 PASSED

- [ ] **Step 1.5: Commit**

```bash
git add src/governiq/webhook/driver.py tests/test_llm_driver_temperature.py
git commit -m "fix: set LLM conversation driver temperature to 0 for deterministic evaluation"
```

---

## Task 2: Wire retry_with_backoff into KoreAPIClient

**Files:**
- Modify: `src/governiq/webhook/kore_api.py`
- Test: `tests/test_kore_api_retry.py`

**Context:** `retry_with_backoff` exists in `src/governiq/webhook/retry.py` but is not used in `kore_api.py`. Transient failures (502, 503, 504, ConnectError) currently cause hard evaluation failures. All four HTTP helpers (`_api_get`, `_api_post`, `_api_get_kore`, `_api_post_kore`) must go through retry.

- [ ] **Step 2.1: Write the failing test**

```python
# tests/test_kore_api_retry.py
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from governiq.webhook.kore_api import KoreAPIClient
from governiq.webhook.jwt_auth import KoreCredentials


@pytest.fixture
def creds():
    return KoreCredentials(
        client_id="cid",
        client_secret="csec",
        bot_id="bid",
        platform_url="https://platform.example.com",
    )


@pytest.mark.asyncio
async def test_api_get_retries_on_503(creds):
    """_api_get should retry when server returns 503."""
    client = KoreAPIClient(creds)
    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            resp = MagicMock()
            resp.status_code = 503
            raise httpx.HTTPStatusError("503", request=MagicMock(), response=resp)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch.object(client, "_ensure_token", AsyncMock(return_value="tok")):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = mock_get
            mock_client_cls.return_value = mock_http

            result = await client._api_get("/test")

    assert call_count == 3
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_api_get_raises_on_non_retryable_error(creds):
    """_api_get should NOT retry on 404."""
    client = KoreAPIClient(creds)

    async def mock_get(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 404
        raise httpx.HTTPStatusError("404", request=MagicMock(), response=resp)

    with patch.object(client, "_ensure_token", AsyncMock(return_value="tok")):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = mock_get
            mock_client_cls.return_value = mock_http

            with pytest.raises(httpx.HTTPStatusError):
                await client._api_get("/test")
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_kore_api_retry.py -v
```

Expected: FAIL — no retry logic present yet

- [ ] **Step 2.3: Add retry import and wrap _api_get**

In `src/governiq/webhook/kore_api.py`, add the import at the top:

```python
from .retry import retry_with_backoff
```

Replace the `_api_get` method body:

```python
async def _api_get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]:
    """Make an authenticated GET request to the Kore.ai API."""
    token = await self._ensure_token()
    url = f"{self.credentials.platform_url}{endpoint}"

    async def _do_get() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()

    return await retry_with_backoff(_do_get, max_retries=3, base_delay=2.0)
```

- [ ] **Step 2.4: Wrap _api_post the same way**

```python
async def _api_post(self, endpoint: str, payload: dict | None = None) -> dict[str, Any]:
    token = await self._ensure_token()
    url = f"{self.credentials.platform_url}{endpoint}"

    async def _do_post() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload or {},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()

    return await retry_with_backoff(_do_post, max_retries=3, base_delay=2.0)
```

- [ ] **Step 2.5: Wrap _api_get_kore and _api_post_kore the same way**

Apply the same inner-function + `retry_with_backoff` pattern to `_api_get_kore` and `_api_post_kore`. The only difference is the header uses `"auth": token` instead of `"Authorization": f"Bearer {token}"`.

- [ ] **Step 2.6: Run tests**

```bash
python -m pytest tests/test_kore_api_retry.py -v
```

Expected: 2 PASSED

- [ ] **Step 2.7: Run full test suite (quick check)**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py -x 2>&1 | tail -20
```

Expected: no new failures

- [ ] **Step 2.8: Commit**

```bash
git add src/governiq/webhook/kore_api.py tests/test_kore_api_retry.py
git commit -m "feat: wire retry_with_backoff into all KoreAPIClient HTTP methods"
```

---

## Task 3: Admin Credentials Required in Submission Form

**Files:**
- Modify: `src/governiq/candidate/routes.py`
- Modify: `src/governiq/templates/candidate_submit.html`
- Test: `tests/test_submission_credentials_required.py`

**Context:** Currently `client_id` and `client_secret` are optional Form fields. Without them, Gate 0 skips the credentials, publish status, and web channel checks. This also means no debug log verification is possible. Make them required.

- [ ] **Step 3.1: Write the failing test**

```python
# tests/test_submission_credentials_required.py
import pytest
from httpx import AsyncClient
from governiq.main import app


@pytest.mark.asyncio
async def test_submit_without_credentials_returns_422():
    """Submission without client_id and client_secret must be rejected."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/candidate/submit",
            data={
                "candidate_name": "Test Candidate",
                "candidate_email": "test@example.com",
                "webhook_url": "https://example.com/v2/hook",
                "bot_id": "bot123",
                # client_id and client_secret intentionally missing
            },
        )
    assert response.status_code == 422
    body = response.json()
    assert "client_id" in str(body).lower() or "credentials" in str(body).lower()
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
python -m pytest tests/test_submission_credentials_required.py -v
```

Expected: FAIL — currently returns 200 or proceeds without credentials

- [ ] **Step 3.3: Make client_id and client_secret required in routes.py**

In `src/governiq/candidate/routes.py`, find:
```python
client_id: str = Form(""),
client_secret: str = Form(""),
```

Change to:
```python
client_id: str = Form(...),
client_secret: str = Form(...),
```

FastAPI will return 422 automatically if either is missing.

- [ ] **Step 3.4: Update the HTML form to mark them as required**

In `src/governiq/templates/candidate_submit.html`, find the `client_id` and `client_secret` inputs and add `required` attribute:

```html
<input type="text" name="client_id" class="form-input" placeholder="Client ID" required>
<input type="password" name="client_secret" class="form-input" placeholder="Client Secret" required>
```

Also add a visible label indicating they are required (e.g. asterisk or "(required)").

- [ ] **Step 3.5: Run test**

```bash
python -m pytest tests/test_submission_credentials_required.py -v
```

Expected: PASS

- [ ] **Step 3.6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py -x 2>&1 | tail -20
```

- [ ] **Step 3.7: Commit**

```bash
git add src/governiq/candidate/routes.py src/governiq/templates/candidate_submit.html tests/test_submission_credentials_required.py
git commit -m "feat: make admin credentials required in submission form"
```

---

## Task 4: Gate 0 — Manifest-Aware Web Channel Severity

**Files:**
- Modify: `src/governiq/core/gate0.py`
- Modify: `src/governiq/core/engine.py`
- Test: `tests/test_gate0_web_driver_severity.py`

**Context:** Currently `_check_web_channel` always returns WARN. If the manifest has WEB_DRIVER tasks, this must return FAIL — evaluation cannot score those tasks without a web channel. `Gate0Checker` needs a `has_web_driver_tasks: bool` parameter.

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_gate0_web_driver_severity.py
import pytest
from governiq.core.gate0 import Gate0Checker, Gate0CheckStatus


BOT_DATA_NO_WEB = {"channelInfos": [{"type": "alexa"}], "publishStatus": "published"}
BOT_DATA_WITH_WEB = {"channelInfos": [{"type": "websdkapp"}], "publishStatus": "published"}


def test_web_channel_missing_is_warn_when_no_web_driver_tasks():
    checker = Gate0Checker(
        webhook_url="https://x.com/v2/hook",
        bot_id="bid",
        backend_api_url="",
        has_web_driver_tasks=False,
    )
    status, _ = checker._check_web_channel(BOT_DATA_NO_WEB)
    assert status == Gate0CheckStatus.WARN


def test_web_channel_missing_is_fail_when_manifest_has_web_driver_tasks():
    checker = Gate0Checker(
        webhook_url="https://x.com/v2/hook",
        bot_id="bid",
        backend_api_url="",
        has_web_driver_tasks=True,
    )
    status, _ = checker._check_web_channel(BOT_DATA_NO_WEB)
    assert status == Gate0CheckStatus.FAIL


def test_web_channel_present_is_always_pass():
    for flag in (True, False):
        checker = Gate0Checker(
            webhook_url="https://x.com/v2/hook",
            bot_id="bid",
            backend_api_url="",
            has_web_driver_tasks=flag,
        )
        status, _ = checker._check_web_channel(BOT_DATA_WITH_WEB)
        assert status == Gate0CheckStatus.PASS
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_gate0_web_driver_severity.py -v
```

Expected: FAIL — `Gate0Checker` does not accept `has_web_driver_tasks` yet

- [ ] **Step 4.3: Add has_web_driver_tasks to Gate0Checker**

In `src/governiq/core/gate0.py`, update `__init__`:

```python
def __init__(
    self,
    webhook_url: str,
    bot_id: str,
    backend_api_url: str,
    kore_api_client: Any | None = None,
    has_web_driver_tasks: bool = False,
):
    self.webhook_url = webhook_url
    self.bot_id = bot_id
    self.backend_api_url = backend_api_url
    self.kore_api_client = kore_api_client
    self.has_web_driver_tasks = has_web_driver_tasks
```

- [ ] **Step 4.4: Update _check_web_channel to use has_web_driver_tasks**

```python
def _check_web_channel(self, bot_data: dict[str, Any]) -> tuple[Gate0CheckStatus, str]:
    """Check channelInfos for a web/mobile SDK channel entry.

    Returns FAIL (not WARN) when manifest has WEB_DRIVER tasks,
    because those tasks cannot be evaluated without a web channel.
    """
    channels = bot_data.get("channelInfos", [])
    channel_types = {c.get("type", "").lower() for c in channels}
    web_types = {"websdkapp", "rtm", "websdk", "web"}
    if channel_types & web_types:
        return Gate0CheckStatus.PASS, "Web channel is enabled."

    if self.has_web_driver_tasks:
        return (
            Gate0CheckStatus.FAIL,
            "Web channel not enabled on your bot. This evaluation includes tasks "
            "that require web driver evaluation and cannot be completed without it. "
            "To enable: XO Platform → Channels → Web/Mobile Client → Enable.",
        )
    return (
        Gate0CheckStatus.WARN,
        "Web channel not enabled on your bot. Tasks requiring web driver evaluation "
        "cannot be tested. All webhook tasks and FAQ will be evaluated normally. "
        "To enable: XO Platform → Channels → Web/Mobile Client → Enable.",
    )
```

- [ ] **Step 4.5: Pass has_web_driver_tasks from engine.run_gate0()**

In `src/governiq/core/engine.py`, update `run_gate0()`:

```python
async def run_gate0(self) -> Gate0Result:
    has_web_driver_tasks = any(
        getattr(t, "ui_policy", None) == UIPolicy.WEB_DRIVER
        for t in self.manifest.tasks
    )
    checker = Gate0Checker(
        webhook_url=self.manifest.webhook_url,
        bot_id=getattr(self.kore_credentials, "bot_id", ""),
        backend_api_url=self.manifest.mock_api_base_url,
        kore_api_client=self.kore_api_client,
        has_web_driver_tasks=has_web_driver_tasks,
    )
    # ... rest unchanged
```

- [ ] **Step 4.6: Run tests**

```bash
python -m pytest tests/test_gate0_web_driver_severity.py tests/test_gate0.py tests/test_engine_gate0.py -v
```

Expected: all PASS

- [ ] **Step 4.7: Commit**

```bash
git add src/governiq/core/gate0.py src/governiq/core/engine.py tests/test_gate0_web_driver_severity.py
git commit -m "feat: gate0 web channel severity is FAIL (not WARN) when manifest has WEB_DRIVER tasks"
```

---

## Task 5: Per-Task Mock API URL

**Files:**
- Modify: `src/governiq/core/manifest.py`
- Modify: `src/governiq/core/engine.py`
- Modify: `src/governiq/candidate/routes.py`
- Modify: `src/governiq/templates/candidate_submit.html`
- Test: `tests/test_per_task_mock_url.py`

**Context:** Candidates may use different mock APIs per task (flight booking API vs hotel API). Add `mock_api_url: str = ""` to `TaskDefinition`. Submission form shows a URL input per task that has a `state_assertion`. Engine uses `task.mock_api_url` when set, else falls back to `manifest.mock_api_base_url`.

- [ ] **Step 5.1: Write failing test**

```python
# tests/test_per_task_mock_url.py
from governiq.core.manifest import TaskDefinition, EnginePattern


def test_task_definition_has_mock_api_url_field():
    task = TaskDefinition(
        task_id="t1",
        task_name="Book Flight",
        pattern=EnginePattern.CREATE,
        dialog_name="BookFlight",
        mock_api_url="https://flight-mock.example.com/api/bookings",
    )
    assert task.mock_api_url == "https://flight-mock.example.com/api/bookings"


def test_task_definition_mock_api_url_defaults_empty():
    task = TaskDefinition(
        task_id="t1",
        task_name="Task",
        pattern=EnginePattern.CREATE,
        dialog_name="D",
    )
    assert task.mock_api_url == ""
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
python -m pytest tests/test_per_task_mock_url.py -v
```

Expected: FAIL — `mock_api_url` field does not exist

- [ ] **Step 5.3: Add mock_api_url to TaskDefinition**

In `src/governiq/core/manifest.py`, inside class `TaskDefinition`, add:

```python
mock_api_url: str = Field(
    default="",
    description="Per-task mock API base URL. Overrides manifest.mock_api_base_url when set. "
                "Provided by candidate at submission time."
)
```

Add this field after `seed_endpoint`.

- [ ] **Step 5.4: Run test to verify it passes**

```bash
python -m pytest tests/test_per_task_mock_url.py -v
```

Expected: 2 PASSED

- [ ] **Step 5.5: Update engine to use per-task mock URL**

In `src/governiq/core/engine.py`, find where `seed_endpoint` / state assertion verification URL is constructed. Add a helper method:

```python
def _task_mock_base_url(self, task: Any) -> str:
    """Return task-specific mock URL if set, else fall back to manifest global."""
    return getattr(task, "mock_api_url", "") or self.manifest.mock_api_base_url
```

Then replace every occurrence of `self.manifest.mock_api_base_url` that is used as a base URL in state inspection / seed calls with `self._task_mock_base_url(task)`.

Search in `engine.py`:
```bash
grep -n "mock_api_base_url" src/governiq/core/engine.py
```

Update each usage to use `self._task_mock_base_url(current_task)`.

- [ ] **Step 5.6: Read per-task mock URLs from submission form**

In `src/governiq/candidate/routes.py`, after reading `mock_api_url` from the form, also read per-task URLs from the request body. The form sends fields named `task_mock_url_{task_id}` for each task that has a `state_assertion`.

Add to the route handler after loading the manifest:

```python
# Read per-task mock API URLs from form (field names: task_mock_url_{task_id})
form_data = await request.form()
for task in manifest.tasks:
    field_name = f"task_mock_url_{task.task_id}"
    if field_name in form_data and form_data[field_name]:
        task.mock_api_url = form_data[field_name]
```

Note: `request` must be available in the route handler. If it's not already a parameter, add `request: Request` as the first parameter.

- [ ] **Step 5.7: Add per-task URL inputs to the submission template**

In `src/governiq/templates/candidate_submit.html`, in the section where the single `mock_api_url` field is shown, replace it with a Jinja2 loop over tasks that have `state_assertion`:

```html
{% for task in manifest.tasks %}
  {% if task.state_assertion and task.state_assertion.enabled %}
  <div class="form-group">
    <label>Mock API URL — {{ task.task_name }}</label>
    <input type="url"
           name="task_mock_url_{{ task.task_id }}"
           class="form-input"
           placeholder="https://mockapi.io/... (for {{ task.task_name }})"
           required>
    <p class="form-hint">This task verifies data against a mock API endpoint. Provide the base URL.</p>
  </div>
  {% endif %}
{% endfor %}
```

If the manifest is not passed to the template yet, it will need to be fetched in the route that renders the form. Check `GET /candidate/submit` route and ensure `manifest` is in the template context.

- [ ] **Step 5.8: Run tests**

```bash
python -m pytest tests/test_per_task_mock_url.py tests/test_manifest.py -v
```

Expected: all PASS

- [ ] **Step 5.9: Commit**

```bash
git add src/governiq/core/manifest.py src/governiq/core/engine.py src/governiq/candidate/routes.py src/governiq/templates/candidate_submit.html tests/test_per_task_mock_url.py
git commit -m "feat: per-task mock API URL in TaskDefinition — candidate provides URL per task at submission"
```

---

## Task 6: Per-Bot Concurrency Guard

**Files:**
- Create: `src/governiq/core/concurrency.py`
- Modify: `src/governiq/api/routes.py` (or wherever evaluation background task is triggered)
- Test: `tests/test_concurrency_guard.py`

**Context:** Two concurrent evaluations of the same bot create cross-contamination risk in debug logs and the bot itself. Enforce max 1 evaluation per bot at a time. Queued submissions wait (not rejected).

- [ ] **Step 6.1: Write failing test**

```python
# tests/test_concurrency_guard.py
import asyncio
import pytest
from governiq.core.concurrency import EvalConcurrencyGuard


@pytest.mark.asyncio
async def test_same_bot_second_eval_waits():
    """Second evaluation for same bot must wait for first to complete."""
    guard = EvalConcurrencyGuard()
    results = []

    async def eval_a():
        async with guard.acquire("bot1"):
            await asyncio.sleep(0.05)
            results.append("a_done")

    async def eval_b():
        async with guard.acquire("bot1"):
            results.append("b_done")

    # Start a, then b — b must wait for a
    await asyncio.gather(eval_a(), eval_b())
    assert results == ["a_done", "b_done"]


@pytest.mark.asyncio
async def test_different_bots_run_concurrently():
    """Different bots must not block each other."""
    guard = EvalConcurrencyGuard()
    results = []

    async def eval_a():
        async with guard.acquire("bot1"):
            await asyncio.sleep(0.05)
            results.append("a")

    async def eval_b():
        async with guard.acquire("bot2"):
            await asyncio.sleep(0.05)
            results.append("b")

    await asyncio.gather(eval_a(), eval_b())
    # Both ran — order may vary
    assert set(results) == {"a", "b"}


@pytest.mark.asyncio
async def test_lock_released_on_exception():
    """Lock must be released even if evaluation raises."""
    guard = EvalConcurrencyGuard()

    async def failing_eval():
        async with guard.acquire("bot1"):
            raise ValueError("boom")

    with pytest.raises(ValueError):
        await failing_eval()

    # Should be able to acquire again immediately
    async with guard.acquire("bot1"):
        pass  # No hang = lock was released
```

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_concurrency_guard.py -v
```

Expected: FAIL — module does not exist

- [ ] **Step 6.3: Create EvalConcurrencyGuard**

Create `src/governiq/core/concurrency.py`:

```python
"""Per-bot evaluation concurrency guard.

Ensures at most one evaluation runs per bot at a time.
Other submissions for the same bot wait (they are not rejected).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class EvalConcurrencyGuard:
    """Maintains one asyncio.Lock per bot ID.

    Usage:
        guard = EvalConcurrencyGuard()
        async with guard.acquire(bot_id):
            await engine.run_full_evaluation(...)
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def _get_lock(self, bot_id: str) -> asyncio.Lock:
        """Get or create the asyncio.Lock for a given bot ID."""
        async with self._meta_lock:
            if bot_id not in self._locks:
                self._locks[bot_id] = asyncio.Lock()
            return self._locks[bot_id]

    @asynccontextmanager
    async def acquire(self, bot_id: str):
        """Async context manager — acquires the per-bot lock, yields, releases."""
        lock = await self._get_lock(bot_id)
        logger.debug("Waiting for evaluation slot for bot %s", bot_id)
        async with lock:
            logger.debug("Evaluation slot acquired for bot %s", bot_id)
            try:
                yield
            finally:
                logger.debug("Evaluation slot released for bot %s", bot_id)
```

- [ ] **Step 6.4: Run tests**

```bash
python -m pytest tests/test_concurrency_guard.py -v
```

Expected: 3 PASSED

- [ ] **Step 6.5: Wire EvalConcurrencyGuard into the evaluation trigger**

In `src/governiq/api/routes.py` (or wherever `run_full_evaluation` is called in the background task), locate the background evaluation function. At the module level, add a module-scoped guard instance:

```python
from ..core.concurrency import EvalConcurrencyGuard
_eval_guard = EvalConcurrencyGuard()
```

Then wrap the evaluation call:

```python
bot_id = getattr(kore_credentials, "bot_id", session_id)
async with _eval_guard.acquire(bot_id):
    scorecard = await engine.run_full_evaluation(...)
```

Find the correct location by searching:
```bash
grep -n "run_full_evaluation\|background_task\|asyncio.create_task" src/governiq/api/routes.py
```

- [ ] **Step 6.6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py -x 2>&1 | tail -20
```

- [ ] **Step 6.7: Commit**

```bash
git add src/governiq/core/concurrency.py src/governiq/api/routes.py tests/test_concurrency_guard.py
git commit -m "feat: per-bot evaluation concurrency guard — one evaluation per bot at a time"
```

---

## Task 7: Timeout Hierarchy

**Files:**
- Modify: `src/governiq/core/engine.py`
- Modify: `src/governiq/webhook/driver.py`
- Test: `tests/test_engine_timeouts.py`

**Context:** Without timeouts, one unresponsive bot blocks the queue indefinitely. Three-tier hierarchy: per-turn 30s → mark turn failed, continue; per-task 3 min → task scored 0, continue; total 30 min → partial results saved, status = `timeout`.

- [ ] **Step 7.1: Write failing tests**

```python
# tests/test_engine_timeouts.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_per_turn_timeout_marks_turn_failed_and_continues():
    """A turn that exceeds 30s must be marked failed; evaluation continues."""
    from governiq.webhook.driver import LLMConversationDriver

    driver = LLMConversationDriver(api_key="test", turn_timeout=0.01)

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(10)  # Much longer than 0.01s timeout

    with patch.object(driver, "_send_message_raw", slow_send):
        result = await driver.send_with_timeout("hello", session_id="s1")

    assert result["timed_out"] is True
    assert "turn_timeout" in result.get("fail_reason", "")


@pytest.mark.asyncio
async def test_total_evaluation_timeout_saves_partial_results():
    """If total evaluation exceeds limit, partial scorecard is returned with timeout status."""
    from governiq.core.engine import EvaluationEngine
    from governiq.core.manifest import Manifest

    # Build a minimal manifest
    manifest_data = {
        "manifest_id": "m1",
        "exam_title": "Test",
        "webhook_url": "https://example.com/v2/hook",
        "tasks": [{"task_id": "t1", "task_name": "T1", "pattern": "CREATE", "dialog_name": "D"}],
        "scoring_config": {"webhook_functional_weight": 1.0, "faq_weight": 0.0, "compliance_weight": 0.0, "pass_threshold": 0.7},
    }
    manifest = Manifest(**manifest_data)
    engine = EvaluationEngine(manifest=manifest, eval_timeout=0.01)

    with patch.object(engine, "_run_cbm_pipeline", AsyncMock(side_effect=asyncio.sleep(10))):
        scorecard = await engine.run_full_evaluation({}, candidate_id="c1", session_id="s1")

    assert scorecard.status == "timeout"
```

- [ ] **Step 7.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_engine_timeouts.py -v
```

Expected: FAIL — `turn_timeout`, `send_with_timeout`, `eval_timeout`, `scorecard.status` not implemented

- [ ] **Step 7.3: Add turn_timeout to LLMConversationDriver**

In `src/governiq/webhook/driver.py`:

1. Add `turn_timeout: float = 30.0` parameter to `__init__`, store as `self.turn_timeout`.

2. Add `send_with_timeout` method:

```python
async def send_with_timeout(self, message: str, session_id: str) -> dict:
    """Send a message with a per-turn timeout.

    Returns a result dict. If timeout fires, sets timed_out=True and fail_reason.
    Never raises — caller can always check result["timed_out"].
    """
    try:
        response = await asyncio.wait_for(
            self._send_message_raw(message, session_id=session_id),
            timeout=self.turn_timeout,
        )
        return {"timed_out": False, "response": response}
    except asyncio.TimeoutError:
        logger.warning(
            "Turn timeout (%.0fs) reached for session %s — marking turn failed",
            self.turn_timeout, session_id,
        )
        return {"timed_out": True, "fail_reason": f"turn_timeout:{self.turn_timeout}s", "response": None}
```

Note: `_send_message_raw` is the inner method that actually does the HTTP call. If the current code has this logic inline in `send_message`, extract it first.

- [ ] **Step 7.4: Add eval_timeout and per-task timeout to EvaluationEngine**

In `src/governiq/core/engine.py`:

1. Add `eval_timeout: float = 1800.0` and `task_timeout: float = 180.0` to `__init__`, store them.

2. Wrap `run_full_evaluation` internals in a total timeout:

```python
async def run_full_evaluation(self, bot_export, candidate_id="", session_id=None) -> Scorecard:
    if session_id is None:
        session_id = str(uuid.uuid4())
    try:
        return await asyncio.wait_for(
            self._run_full_evaluation_inner(bot_export, candidate_id, session_id),
            timeout=self.eval_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Total evaluation timeout (%.0fs) reached for session %s — saving partial results",
            self.eval_timeout, session_id,
        )
        scorecard = self._build_partial_scorecard(session_id, candidate_id)
        scorecard.status = "timeout"
        self._persist_scorecard(scorecard, session_id)
        return scorecard
```

Rename current `run_full_evaluation` body to `_run_full_evaluation_inner`.

3. Wrap per-task execution in `_run_full_evaluation_inner`:

```python
try:
    task_score = await asyncio.wait_for(
        self._run_task(task, session_id, ...),
        timeout=self.task_timeout,
    )
except asyncio.TimeoutError:
    logger.warning(
        "Task timeout (%.0fs) for task %s — scoring as 0",
        self.task_timeout, task.task_id,
    )
    task_score = TaskScore(task_id=task.task_id, task_name=task.task_name)
    task_score.webhook_score = 0.0
    task_score.timeout = True
scorecard.task_scores.append(task_score)
```

- [ ] **Step 7.5: Add status field to Scorecard (if not present)**

Check `src/governiq/core/scoring.py`:
```bash
grep -n "status\|class Scorecard" src/governiq/core/scoring.py
```

If `Scorecard` lacks a `status` field, add:
```python
status: str = "complete"  # "complete" | "timeout" | "error"
```

- [ ] **Step 7.6: Run tests**

```bash
python -m pytest tests/test_engine_timeouts.py -v
```

Expected: 2 PASSED

- [ ] **Step 7.7: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py -x 2>&1 | tail -20
```

- [ ] **Step 7.8: Commit**

```bash
git add src/governiq/core/engine.py src/governiq/webhook/driver.py src/governiq/core/scoring.py tests/test_engine_timeouts.py
git commit -m "feat: three-tier timeout hierarchy — per-turn 30s, per-task 3min, total 30min with partial results"
```

---

## Task 8: Debug Log Verifier Module

**Files:**
- Create: `src/governiq/webhook/debug_log_verifier.py`
- Test: `tests/test_debug_log_verifier.py`

**Context:** After each webhook turn, we want to verify what the bot actually did internally. The Kore.ai debug log API is polled (every 1s, up to 10s). If it confirms the expected intent/service call, we record `verified=True, source="debug_log"`. On timeout, we set `source="timeout"` and the caller falls back to mock API. `get_debug_logs` already exists in `KoreAPIClient`.

- [ ] **Step 8.1: Write failing tests**

```python
# tests/test_debug_log_verifier.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from governiq.webhook.debug_log_verifier import DebugLogVerifier, DebugLogResult


def make_mock_kore_client(log_entries=None, fail_until_call=0):
    """Create a mock KoreAPIClient. fail_until_call simulates latency."""
    client = MagicMock()
    call_count = [0]

    async def mock_get_debug_logs(session_id, limit=100):
        call_count[0] += 1
        if call_count[0] <= fail_until_call:
            return {"entries": []}
        return {"entries": log_entries or []}

    client.get_debug_logs = mock_get_debug_logs
    return client


@pytest.mark.asyncio
async def test_returns_verified_when_log_has_entries():
    entries = [{"type": "intent", "name": "BookFlight", "status": "success"}]
    client = make_mock_kore_client(log_entries=entries)
    verifier = DebugLogVerifier(client, poll_interval=0.01, poll_timeout=1.0)

    result = await verifier.verify_turn(session_id="s1")

    assert result.verified is True
    assert result.source == "debug_log"
    assert len(result.raw_entries) > 0


@pytest.mark.asyncio
async def test_returns_timeout_when_no_entries_within_budget():
    client = make_mock_kore_client(log_entries=[])  # Always empty
    verifier = DebugLogVerifier(client, poll_interval=0.01, poll_timeout=0.05)

    result = await verifier.verify_turn(session_id="s1")

    assert result.verified is False
    assert result.source == "timeout"


@pytest.mark.asyncio
async def test_polls_multiple_times_before_entries_appear():
    """Verifier must keep polling; entries appear on 3rd call."""
    entries = [{"type": "service", "name": "SaveBooking", "status": "success"}]
    client = make_mock_kore_client(log_entries=entries, fail_until_call=2)
    verifier = DebugLogVerifier(client, poll_interval=0.01, poll_timeout=1.0)

    result = await verifier.verify_turn(session_id="s1")

    assert result.verified is True
    assert result.source == "debug_log"


@pytest.mark.asyncio
async def test_returns_no_kore_client_source_when_client_is_none():
    verifier = DebugLogVerifier(kore_api_client=None)
    result = await verifier.verify_turn(session_id="s1")
    assert result.source == "no_client"
    assert result.verified is False
```

- [ ] **Step 8.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_debug_log_verifier.py -v
```

Expected: FAIL — module does not exist

- [ ] **Step 8.3: Create DebugLogVerifier**

Create `src/governiq/webhook/debug_log_verifier.py`:

```python
"""Per-turn debug log verification.

After each webhook turn, polls Kore.ai debug logs for this session.
Returns verified=True when log entries appear, source="debug_log".
On timeout, returns verified=False, source="timeout" — caller falls
back to mock API verification.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class DebugLogResult:
    verified: bool = False
    source: Literal["debug_log", "timeout", "no_client", "error"] = "timeout"
    raw_entries: list[dict] = field(default_factory=list)
    matched_intent: str | None = None
    matched_service: str | None = None


class DebugLogVerifier:
    """Polls Kore.ai debug logs per turn to verify bot execution.

    Args:
        kore_api_client: KoreAPIClient instance (or None — verification skipped).
        poll_interval: Seconds between polls (default 1.0).
        poll_timeout: Maximum seconds to wait for entries (default 10.0).
    """

    def __init__(
        self,
        kore_api_client: Any | None = None,
        poll_interval: float = 1.0,
        poll_timeout: float = 10.0,
    ):
        self.client = kore_api_client
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def verify_turn(
        self,
        session_id: str,
        expected_intent: str | None = None,
        expected_service_call: str | None = None,
    ) -> DebugLogResult:
        """Poll debug logs until entries appear or timeout fires.

        Returns DebugLogResult. Never raises.
        """
        if self.client is None:
            return DebugLogResult(verified=False, source="no_client")

        deadline = asyncio.get_event_loop().time() + self.poll_timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                data = await self.client.get_debug_logs(session_id)
                entries = data.get("entries", [])
                if entries:
                    result = DebugLogResult(
                        verified=True,
                        source="debug_log",
                        raw_entries=entries,
                    )
                    result.matched_intent = self._find_intent(entries, expected_intent)
                    result.matched_service = self._find_service(entries, expected_service_call)
                    return result
            except Exception as exc:
                logger.warning("Debug log poll error for session %s: %s", session_id, exc)

            await asyncio.sleep(self.poll_interval)

        logger.warning(
            "Debug log timeout (%.0fs) for session %s — falling back to mock API",
            self.poll_timeout, session_id,
        )
        return DebugLogResult(verified=False, source="timeout")

    def _find_intent(self, entries: list[dict], expected: str | None) -> str | None:
        for entry in entries:
            if entry.get("type") == "intent":
                name = entry.get("name", "")
                if expected is None or name == expected:
                    return name
        return None

    def _find_service(self, entries: list[dict], expected: str | None) -> str | None:
        for entry in entries:
            if entry.get("type") == "service":
                name = entry.get("name", "")
                if expected is None or name == expected:
                    return name
        return None
```

- [ ] **Step 8.4: Run tests**

```bash
python -m pytest tests/test_debug_log_verifier.py -v
```

Expected: 4 PASSED

- [ ] **Step 8.5: Commit**

```bash
git add src/governiq/webhook/debug_log_verifier.py tests/test_debug_log_verifier.py
git commit -m "feat: DebugLogVerifier — per-turn Kore debug log polling with timeout and fallback"
```

---

## Task 9: Wire Debug Log Verification into Driver

**Files:**
- Modify: `src/governiq/webhook/driver.py`
- Modify: `src/governiq/core/engine.py`
- Test: `tests/test_driver_debug_log_integration.py`

**Context:** `LLMConversationDriver` gets a `DebugLogVerifier | None`. After each turn's webhook response, it calls `verifier.verify_turn(session_id)`. If `source == "timeout"`, the driver falls back to mock API verification (existing path). The result is stored on the turn record for the scorecard.

- [ ] **Step 9.1: Write failing test**

```python
# tests/test_driver_debug_log_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from governiq.webhook.driver import LLMConversationDriver
from governiq.webhook.debug_log_verifier import DebugLogVerifier, DebugLogResult


@pytest.mark.asyncio
async def test_driver_calls_debug_log_verifier_after_turn():
    """After send_with_timeout, driver must call verifier.verify_turn."""
    mock_verifier = MagicMock()
    mock_verifier.verify_turn = AsyncMock(
        return_value=DebugLogResult(verified=True, source="debug_log", raw_entries=[{"type": "intent"}])
    )

    driver = LLMConversationDriver(api_key="test", debug_log_verifier=mock_verifier)

    with patch.object(driver, "_send_message_raw", AsyncMock(return_value={"messages": []})):
        result = await driver.send_with_timeout("hello", session_id="s1")

    mock_verifier.verify_turn.assert_called_once_with(session_id="s1")
    assert result.get("debug_log_source") == "debug_log"


@pytest.mark.asyncio
async def test_driver_skips_debug_log_when_no_verifier():
    """Driver must not crash when debug_log_verifier is None."""
    driver = LLMConversationDriver(api_key="test", debug_log_verifier=None)

    with patch.object(driver, "_send_message_raw", AsyncMock(return_value={"messages": []})):
        result = await driver.send_with_timeout("hello", session_id="s1")

    assert result.get("timed_out") is False
    assert "debug_log_source" not in result  # No verifier = no debug log field
```

- [ ] **Step 9.2: Run tests to verify they fail**

```bash
python -m pytest tests/test_driver_debug_log_integration.py -v
```

Expected: FAIL — `debug_log_verifier` parameter not on driver

- [ ] **Step 9.3: Add debug_log_verifier to LLMConversationDriver**

In `src/governiq/webhook/driver.py`:

1. Import `DebugLogVerifier` at the top:
```python
from .debug_log_verifier import DebugLogVerifier
```

2. Add to `__init__`:
```python
debug_log_verifier: DebugLogVerifier | None = None,
```
Store as `self._debug_log_verifier = debug_log_verifier`.

3. Update `send_with_timeout` to call the verifier after a successful response:

```python
async def send_with_timeout(self, message: str, session_id: str) -> dict:
    try:
        response = await asyncio.wait_for(
            self._send_message_raw(message, session_id=session_id),
            timeout=self.turn_timeout,
        )
        result = {"timed_out": False, "response": response}

        if self._debug_log_verifier is not None:
            debug_result = await self._debug_log_verifier.verify_turn(session_id=session_id)
            result["debug_log_verified"] = debug_result.verified
            result["debug_log_source"] = debug_result.source
            result["debug_log_entries"] = debug_result.raw_entries

        return result
    except asyncio.TimeoutError:
        logger.warning(
            "Turn timeout (%.0fs) reached for session %s — marking turn failed",
            self.turn_timeout, session_id,
        )
        return {"timed_out": True, "fail_reason": f"turn_timeout:{self.turn_timeout}s", "response": None}
```

- [ ] **Step 9.4: Build DebugLogVerifier in EvaluationEngine and pass to driver**

In `src/governiq/core/engine.py`:

1. Import:
```python
from ..webhook.debug_log_verifier import DebugLogVerifier
```

2. In `__init__`, after `self.kore_api_client` is assigned, build the verifier:
```python
debug_log_verifier = None
if self.kore_api_client:
    debug_log_verifier = DebugLogVerifier(
        kore_api_client=self.kore_api_client,
        poll_interval=1.0,
        poll_timeout=10.0,
    )
self.driver = LLMConversationDriver(
    ...existing args...,
    debug_log_verifier=debug_log_verifier,
)
```

- [ ] **Step 9.5: Run tests**

```bash
python -m pytest tests/test_driver_debug_log_integration.py tests/test_debug_log_verifier.py -v
```

Expected: all PASS

- [ ] **Step 9.6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -20
```

- [ ] **Step 9.7: Commit**

```bash
git add src/governiq/webhook/driver.py src/governiq/core/engine.py tests/test_driver_debug_log_integration.py
git commit -m "feat: wire DebugLogVerifier into conversation driver — per-turn debug log verification with mock API fallback"
```

---

## Final Check

- [ ] **Run full test suite one last time**

```bash
python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -30
```

Expected: all previously passing tests still pass, all new tests pass.

---

## What comes next

**Tasks 11, 12, 13** in the previous plan (`2026-03-26-core-pipeline-improvements.md`):
- Task 11: Gate 0 distinct portal status
- Task 12: FAQ driver template warning
- Task 13: Starlette deprecation fix

**Plan 2 — Web Driver:** `KoreWebDriver` (Playwright + Kore.ai Web SDK), GovernIQ host page, JWT session token endpoint. Depends on `UIPolicy.WEB_DRIVER` enum from the prior sprint.
