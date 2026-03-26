# Core Evaluation Pipeline Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the architecture spec's core runtime improvements: Gate 0 hardening, live FAQ semantic evaluation, Response Type Detector, and Semantic Field Mapper.

**Architecture:** Gate 0 gains a consolidated Bot Details API call (credentials + publish status + web channel in one call) plus a V2 webhook check. FAQ evaluation moves from structural CBM keyword-matching to live webhook conversations scored by multilingual sentence-transformers. The webhook pipeline gains a Response Type Detector that classifies each bot response, and a Semantic Field Mapper that handles button/form/carousel JSON responses via manifest entity matching — enabling rich UI interaction on the webhook path (no browser required for webhook-served UI).

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, sentence-transformers (`paraphrase-multilingual-mpnet-base-v2`), httpx, pytest

---

## Scope note — what is NOT in this plan

Two subsystems from the architecture spec are **separate plans**:

- **Web Driver (Plan 2):** KoreWebDriver (Playwright + Kore.ai Web SDK), GovernIQ host page, JWT endpoint — requires Playwright browser infrastructure
- **Platform Assumption Workbench (Plan 3):** Pre-build API verification test suite — a developer tool, not a runtime component

Both depend on this plan (uiPolicy enum, FAQTask schema) being complete first.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/governiq/core/manifest.py` | Modify | Add `UIPolicy` enum, `FAQTask` model; add `ui_policy` to `TaskDefinition`; add `faq_tasks` to `Manifest` |
| `src/governiq/core/manifest_validator.py` | Modify | Add MD-13 rule: FAQ task missing `similarity_threshold` |
| `src/governiq/webhook/kore_api.py` | Modify | Add `get_bot_details(bot_id)` method |
| `src/governiq/core/gate0.py` | Create | `Gate0Checker` — runs the four pre-evaluation checks; returns `Gate0Result` |
| `src/governiq/core/engine.py` | Modify | Call `Gate0Checker` before Gate 1; add FAILED_CONNECTIVITY handling; call FAQ evaluator after webhook tasks |
| `src/governiq/webhook/faq_evaluator.py` | Create | `FAQEvaluator` — sends FAQ questions via webhook driver, scores responses with sentence-transformers |
| `src/governiq/webhook/response_type_detector.py` | Create | `detect_response_type(messages)` — classifies webhook `data[]` as `text`, `buttons`, `inline_form`, `carousel`, or `external_url` |
| `src/governiq/webhook/semantic_field_mapper.py` | Create | `SemanticFieldMapper` — maps detected UI elements to manifest entities; returns the webhook payload to send |
| `src/governiq/webhook/driver.py` | Modify | Integrate Response Type Detector; route non-text responses to Semantic Field Mapper |
| `tests/test_manifest_faq_task.py` | Create | FAQTask model + UIPolicy enum |
| `tests/test_manifest_validator_faq.py` | Create | MD-13 rule |
| `tests/test_gate0.py` | Create | Gate0Checker unit tests |
| `tests/test_faq_evaluator.py` | Create | FAQEvaluator unit + integration tests |
| `tests/test_response_type_detector.py` | Create | Response type classification tests |
| `tests/test_semantic_field_mapper.py` | Create | Entity mapping tests |

---

## Task 1: Manifest Schema — FAQTask + UIPolicy

**Files:**
- Modify: `src/governiq/core/manifest.py`
- Create: `tests/test_manifest_faq_task.py`

### What to add

`UIPolicy` goes into the enums block. `FAQTask` goes between `FAQConfig` and `ComplianceCheck`. `ui_policy` field goes on `TaskDefinition`. `faq_tasks` goes on `Manifest`.

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/test_manifest_faq_task.py
import pytest
from pydantic import ValidationError
from governiq.core.manifest import FAQTask, UIPolicy, Manifest, TaskDefinition, EnginePattern


class TestUIPolicy:
    def test_default_is_prefer_webhook(self):
        # TaskDefinition must default ui_policy to prefer_webhook
        # Build the minimal required fields inline (use a real manifest for full test)
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
        )
        assert td.ui_policy == UIPolicy.PREFER_WEBHOOK

    def test_web_driver_value(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
            ui_policy="web_driver",
        )
        assert td.ui_policy == UIPolicy.WEB_DRIVER

    def test_invalid_value_rejected(self):
        with pytest.raises(ValidationError):
            TaskDefinition(
                task_id="t1",
                task_name="Task 1",
                pattern=EnginePattern.CREATE,
                dialog_name="Book",
                ui_policy="allow_playwright",  # undefined — must be rejected
            )


class TestFAQTask:
    def test_valid_faq_task(self):
        task = FAQTask(
            task_id="FAQ-HOURS",
            question="What are your opening hours?",
            expected_answer="Open 9 AM to 5 PM Monday to Saturday.",
            similarity_threshold=0.80,
        )
        assert task.task_id == "FAQ-HOURS"
        assert task.similarity_threshold == 0.80

    def test_similarity_threshold_required(self):
        with pytest.raises(ValidationError):
            FAQTask(
                task_id="FAQ-HOURS",
                question="What are your opening hours?",
                expected_answer="Open 9 AM to 5 PM.",
                # missing similarity_threshold
            )

    def test_threshold_bounds(self):
        with pytest.raises(ValidationError):
            FAQTask(
                task_id="FAQ-X",
                question="q",
                expected_answer="a",
                similarity_threshold=1.5,  # > 1.0 — invalid
            )

    def test_alternative_questions_optional(self):
        task = FAQTask(
            task_id="FAQ-X",
            question="q",
            expected_answer="a",
            similarity_threshold=0.75,
        )
        assert task.alternative_questions == []


class TestManifestFAQTasks:
    def test_manifest_accepts_faq_tasks(self):
        # Load the medical manifest and inject faq_tasks
        import json
        from pathlib import Path
        path = Path("manifests/medical_appointment_basic.json")
        data = json.loads(path.read_text())
        data["faq_tasks"] = [
            {
                "task_id": "FAQ-HOURS",
                "question": "What are your opening hours?",
                "expected_answer": "9 AM to 5 PM, Monday to Saturday.",
                "similarity_threshold": 0.80,
            }
        ]
        m = Manifest(**data)
        assert len(m.faq_tasks) == 1
        assert m.faq_tasks[0].task_id == "FAQ-HOURS"

    def test_faq_tasks_defaults_to_empty(self):
        import json
        from pathlib import Path
        data = json.loads(Path("manifests/medical_appointment_basic.json").read_text())
        m = Manifest(**data)
        assert m.faq_tasks == []
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
cd /c/Users/gvkir/Documents/EvalAutomaton
venv/Scripts/python -m pytest tests/test_manifest_faq_task.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'FAQTask'` (or similar)

- [ ] **Step 1.3: Add UIPolicy enum to manifest.py**

In `src/governiq/core/manifest.py`, after the `EnginePattern` class and before `DialogNamePolicy`:

```python
class UIPolicy(str, Enum):
    """Routing policy — which driver handles this task's UI interaction."""
    PREFER_WEBHOOK = "prefer_webhook"   # All interaction via webhook JSON (default)
    WEB_DRIVER = "web_driver"           # Full Playwright web driver (Kore.ai Web SDK)
    UNTESTABLE_FLAG = "untestable_flag" # Requires manual evaluation
```

- [ ] **Step 1.4: Add FAQTask model to manifest.py**

After the `FAQConfig` class (around line 166):

```python
class FAQTask(BaseModel):
    """A single FAQ evaluated live via webhook + semantic similarity.

    The webhook driver sends `question` in an isolated session.
    The bot's response is compared against `expected_answer` using
    a multilingual sentence-transformers model. Pass if similarity
    >= similarity_threshold.
    """
    task_id: str = Field(..., description="Unique FAQ task ID, e.g. 'FAQ-HOURS'")
    topic: str = Field(default="", description="Short topic label for display")
    question: str = Field(..., description="Question to send to the bot")
    alternative_questions: list[str] = Field(
        default_factory=list,
        description="Alternative phrasings — used for CBM structural check only",
    )
    expected_answer: str = Field(
        ...,
        description="Canonical answer from the knowledge graph. "
                    "The bot response is compared against this.",
    )
    similarity_threshold: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to pass. Required — Manifest Readiness "
                    "Validator raises MD-13 if missing.",
    )
    scoring: dict[str, Any] = Field(
        default_factory=dict,
        description="{'type': 'binary', 'maxPoints': N}",
    )
```

- [ ] **Step 1.5: Add ui_policy to TaskDefinition**

In `TaskDefinition`, after the `weight` field:

```python
# Driver routing policy
ui_policy: UIPolicy = Field(
    default=UIPolicy.PREFER_WEBHOOK,
    description="Determines which driver evaluates this task's UI interaction.",
)
```

- [ ] **Step 1.6: Add faq_tasks to Manifest**

In the `Manifest` class, after the `faq_config` field:

```python
# Live FAQ evaluation tasks (semantic similarity via sentence-transformers)
faq_tasks: list[FAQTask] = Field(
    default_factory=list,
    description="FAQ questions to send via webhook driver. "
                "Evaluated by multilingual semantic similarity, not keyword matching.",
)
```

Also add `FAQTask` and `UIPolicy` to the module's imports in any file that needs them.

- [ ] **Step 1.7: Run tests — verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_manifest_faq_task.py -v
```

Expected: all tests PASS

- [ ] **Step 1.8: Run full test suite — no regressions**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -20
```

Expected: all existing tests still pass

- [ ] **Step 1.9: Commit**

```bash
git add src/governiq/core/manifest.py tests/test_manifest_faq_task.py
git commit -m "feat: add FAQTask model and UIPolicy enum to manifest schema"
```

---

## Task 2: Manifest Readiness Validator — MD-13 (FAQ missing threshold)

**Files:**
- Modify: `src/governiq/core/manifest_validator.py`
- Create: `tests/test_manifest_validator_faq.py`

### What it does

Rule MD-13 runs when `manifest.faq_tasks` is non-empty. It raises `ERROR` for any FAQ task where `similarity_threshold` is missing (Pydantic already enforces this — so MD-13 is a belt-and-suspenders check at the validator level for manifests loaded from dict without schema enforcement, e.g., partially migrated manifests).

Actually, since Pydantic v2 enforces `similarity_threshold` as required, MD-13's real value is flagging FAQ tasks where `expected_answer` is an empty string (an authoring mistake).

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_manifest_validator_faq.py
import json
from pathlib import Path
import pytest
from governiq.core.manifest import FAQTask, Manifest
from governiq.core.manifest_validator import Severity, validate_manifest


def _manifest_with_faq_tasks(extra_tasks=None):
    """Load medical manifest and inject faq_tasks."""
    data = json.loads(Path("manifests/medical_appointment_basic.json").read_text())
    data["faq_tasks"] = extra_tasks or [
        {
            "task_id": "FAQ-HOURS",
            "question": "What are your hours?",
            "expected_answer": "9 AM to 5 PM.",
            "similarity_threshold": 0.80,
        }
    ]
    return Manifest(**data)


class TestMD13:
    def test_valid_faq_task_no_defect(self):
        m = _manifest_with_faq_tasks()
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert md13 == []

    def test_empty_expected_answer_raises_error(self):
        m = _manifest_with_faq_tasks([
            {
                "task_id": "FAQ-HOURS",
                "question": "What are your hours?",
                "expected_answer": "",   # empty — evaluator forgot to fill in
                "similarity_threshold": 0.80,
            }
        ])
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert len(md13) == 1
        assert md13[0].severity == Severity.ERROR
        assert md13[0].task_id == "FAQ-HOURS"

    def test_empty_question_raises_error(self):
        m = _manifest_with_faq_tasks([
            {
                "task_id": "FAQ-X",
                "question": "",           # empty question
                "expected_answer": "valid answer",
                "similarity_threshold": 0.80,
            }
        ])
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert len(md13) == 1
        assert md13[0].task_id == "FAQ-X"

    def test_no_faq_tasks_no_defect(self):
        data = json.loads(Path("manifests/medical_appointment_basic.json").read_text())
        m = Manifest(**data)
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert md13 == []
```

- [ ] **Step 2.2: Run tests — verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_manifest_validator_faq.py -v 2>&1 | head -20
```

Expected: FAIL (MD-13 rule doesn't exist yet)

- [ ] **Step 2.3: Add MD-13 rule to manifest_validator.py**

In `validate_manifest`, add after the existing rule calls:

```python
defects.extend(_md13_faq_task_empty_fields(manifest))
```

Then add the rule function at the bottom of the file:

```python
def _md13_faq_task_empty_fields(manifest: Manifest) -> list[ManifestDefect]:
    """MD-13: FAQ task has empty question or expected_answer."""
    defects = []
    for faq in manifest.faq_tasks:
        if not faq.question.strip():
            defects.append(ManifestDefect(
                rule_id="MD-13",
                severity=Severity.ERROR,
                message=(
                    f"FAQ task '{faq.task_id}' has an empty question. "
                    "The question field is required for live FAQ evaluation."
                ),
                task_id=faq.task_id,
                field_path="question",
            ))
        if not faq.expected_answer.strip():
            defects.append(ManifestDefect(
                rule_id="MD-13",
                severity=Severity.ERROR,
                message=(
                    f"FAQ task '{faq.task_id}' has an empty expected_answer. "
                    "Provide the canonical answer from the knowledge graph "
                    "so semantic similarity can be computed."
                ),
                task_id=faq.task_id,
                field_path="expected_answer",
            ))
    return defects
```

Also add `FAQTask` to the imports at the top of `manifest_validator.py`:

```python
from .manifest import (
    DialogNamePolicy,
    EnginePattern,
    FAQTask,
    Manifest,
    TaskDefinition,
)
```

- [ ] **Step 2.4: Run tests — verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_manifest_validator_faq.py -v
```

- [ ] **Step 2.5: Run full test suite**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -10
```

- [ ] **Step 2.6: Commit**

```bash
git add src/governiq/core/manifest_validator.py tests/test_manifest_validator_faq.py
git commit -m "feat: add MD-13 validator rule for empty FAQ task fields"
```

---

## Task 3: Gate 0 Hardening — Bot Details API + V2 Webhook Check

**Files:**
- Modify: `src/governiq/webhook/kore_api.py`
- Create: `src/governiq/core/gate0.py`
- Create: `tests/test_gate0.py`

### What it does

`Gate0Checker` runs four checks before Gate 1 (CBM parse):
1. Webhook reachability (ON_CONNECT probe)
2. Bot Details API — single call with three sub-checks: credentials (2a), publish status (2b), web channel (2c)
3. Backend API reachability
4. Webhook V2 URL check

Returns `Gate0Result` with per-check status. Any FAIL → block evaluation. WARN → continue with note.

- [ ] **Step 3.1: Add `get_bot_details` to KoreAPIClient**

In `src/governiq/webhook/kore_api.py`, add this method to `KoreAPIClient`:

```python
async def get_bot_details(self, bot_id: str) -> dict[str, Any]:
    """Fetch bot metadata via GET /api/public/bot/{botId}.

    Returns the full response dict. Raises httpx.HTTPStatusError on 401/404.
    Caller inspects the dict for publish status and enabled channels.
    """
    return await self._api_get(f"/api/public/bot/{bot_id}")
```

- [ ] **Step 3.2: Write the failing tests**

```python
# tests/test_gate0.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from governiq.core.gate0 import Gate0Checker, Gate0Result, Gate0CheckStatus


class TestGate0CheckStatus:
    def test_result_is_pass_only_when_all_pass(self):
        result = Gate0Result(checks={
            "webhook_reachability": Gate0CheckStatus.PASS,
            "bot_credentials": Gate0CheckStatus.PASS,
            "bot_published": Gate0CheckStatus.PASS,
            "web_channel": Gate0CheckStatus.WARN,
            "backend_api": Gate0CheckStatus.PASS,
            "webhook_version": Gate0CheckStatus.PASS,
        })
        assert result.can_proceed is True  # WARN does not block

    def test_any_fail_blocks(self):
        result = Gate0Result(checks={
            "webhook_reachability": Gate0CheckStatus.PASS,
            "bot_credentials": Gate0CheckStatus.FAIL,
            "bot_published": Gate0CheckStatus.PASS,
            "web_channel": Gate0CheckStatus.PASS,
            "backend_api": Gate0CheckStatus.PASS,
            "webhook_version": Gate0CheckStatus.PASS,
        })
        assert result.can_proceed is False

    def test_v2_check_pass_on_v2_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/v2/bot123")
        assert status == Gate0CheckStatus.PASS

    def test_v2_check_fail_on_v1_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/v1/bot123")
        assert status == Gate0CheckStatus.FAIL
        assert "V2" in msg

    def test_v2_check_warn_on_ambiguous_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/bot123")
        assert status == Gate0CheckStatus.WARN

    def test_web_channel_warn_when_absent(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"channelInfos": [{"type": "webhook"}]}
        status, msg = checker._check_web_channel(bot_response)
        assert status == Gate0CheckStatus.WARN

    def test_web_channel_pass_when_present(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"channelInfos": [{"type": "webhook"}, {"type": "websdkapp"}]}
        status, msg = checker._check_web_channel(bot_response)
        assert status == Gate0CheckStatus.PASS

    def test_publish_status_fail_when_not_published(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"publishStatus": "inProgress"}
        status, msg = checker._check_publish_status(bot_response)
        assert status == Gate0CheckStatus.FAIL
        assert "published" in msg.lower()

    def test_publish_status_pass(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"publishStatus": "published"}
        status, msg = checker._check_publish_status(bot_response)
        assert status == Gate0CheckStatus.PASS
```

- [ ] **Step 3.3: Run tests — verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_gate0.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'Gate0Checker'`

- [ ] **Step 3.4: Create `src/governiq/core/gate0.py`**

```python
"""Gate 0 — Pre-evaluation connectivity and credential checks.

Runs four checks before Gate 1 (CBM parse). Any FAIL blocks evaluation
and returns an actionable error to the candidate. WARN proceeds with a note.

Checks:
  1. webhook_reachability  — ON_CONNECT probe to the candidate's webhook URL
  2. bot_credentials       — GET /api/public/bot/{botId} with admin JWT (401/404 = FAIL)
  3. bot_published         — publishStatus field in Bot Details response
  4. web_channel           — channelInfos list in Bot Details response (WARN not FAIL)
  5. backend_api           — GET to mock API URL (any response = reachable)
  6. webhook_version       — URL path must contain /v2/ (V1 = FAIL, ambiguous = WARN)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class Gate0CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"   # check not applicable (e.g. no web driver tasks in manifest)


@dataclass
class Gate0Result:
    checks: dict[str, Gate0CheckStatus] = field(default_factory=dict)
    messages: dict[str, str] = field(default_factory=dict)

    @property
    def can_proceed(self) -> bool:
        """True if no check returned FAIL."""
        return Gate0CheckStatus.FAIL not in self.checks.values()

    @property
    def web_channel_available(self) -> bool:
        return self.checks.get("web_channel") == Gate0CheckStatus.PASS


class Gate0Checker:
    """Runs all Gate 0 checks for a submission."""

    def __init__(
        self,
        webhook_url: str,
        bot_id: str,
        backend_api_url: str,
        kore_api_client: Any | None = None,  # KoreAPIClient
    ):
        self.webhook_url = webhook_url
        self.bot_id = bot_id
        self.backend_api_url = backend_api_url
        self.kore_api_client = kore_api_client

    async def run(self) -> Gate0Result:
        """Execute all checks and return the combined result."""
        result = Gate0Result()

        # Check 4: V2 webhook version (fast, no network)
        status, msg = self._check_webhook_version(self.webhook_url)
        result.checks["webhook_version"] = status
        result.messages["webhook_version"] = msg
        if status == Gate0CheckStatus.FAIL:
            return result  # No point checking reachability if URL is wrong

        # Check 3: Backend API reachability
        status, msg = await self._check_backend_api(self.backend_api_url)
        result.checks["backend_api"] = status
        result.messages["backend_api"] = msg

        # Check 1: Webhook reachability (no auth probe — just connectivity)
        status, msg = await self._check_webhook_reachability(self.webhook_url)
        result.checks["webhook_reachability"] = status
        result.messages["webhook_reachability"] = msg

        # Check 2: Bot Details API — single call, three sub-checks
        if self.kore_api_client:
            await self._run_bot_details_checks(result)
        else:
            result.checks["bot_credentials"] = Gate0CheckStatus.SKIP
            result.checks["bot_published"] = Gate0CheckStatus.SKIP
            result.checks["web_channel"] = Gate0CheckStatus.SKIP
            result.messages["bot_credentials"] = "Admin credentials not provided — bot details checks skipped."

        return result

    async def _run_bot_details_checks(self, result: Gate0Result) -> None:
        """Single GET /api/public/bot/{botId} → sub-checks 2a, 2b, 2c."""
        try:
            bot_data = await self.kore_api_client.get_bot_details(self.bot_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                result.checks["bot_credentials"] = Gate0CheckStatus.FAIL
                result.messages["bot_credentials"] = (
                    "Invalid admin credentials. Check your Admin Client ID and Secret."
                )
            elif e.response.status_code == 404:
                result.checks["bot_credentials"] = Gate0CheckStatus.FAIL
                result.messages["bot_credentials"] = (
                    f"Bot ID '{self.bot_id}' not found. "
                    "Verify the Bot ID in XO Platform: Settings → Bot ID."
                )
            else:
                result.checks["bot_credentials"] = Gate0CheckStatus.FAIL
                result.messages["bot_credentials"] = f"Bot Details API error: {e.response.status_code}"
            # Sub-checks 2b and 2c cannot run without bot data
            result.checks["bot_published"] = Gate0CheckStatus.SKIP
            result.checks["web_channel"] = Gate0CheckStatus.SKIP
            return
        except Exception as e:
            result.checks["bot_credentials"] = Gate0CheckStatus.FAIL
            result.messages["bot_credentials"] = f"Bot Details API unreachable: {e}"
            result.checks["bot_published"] = Gate0CheckStatus.SKIP
            result.checks["web_channel"] = Gate0CheckStatus.SKIP
            return

        # 2a: credentials valid (200 response)
        result.checks["bot_credentials"] = Gate0CheckStatus.PASS
        result.messages["bot_credentials"] = "Admin credentials valid."

        # 2b: publish status
        status, msg = self._check_publish_status(bot_data)
        result.checks["bot_published"] = status
        result.messages["bot_published"] = msg

        # 2c: web channel (WARN not FAIL)
        status, msg = self._check_web_channel(bot_data)
        result.checks["web_channel"] = status
        result.messages["web_channel"] = msg

    def _check_publish_status(self, bot_data: dict[str, Any]) -> tuple[Gate0CheckStatus, str]:
        """Check publishStatus field. 'published' = PASS, anything else = FAIL."""
        publish_status = bot_data.get("publishStatus", "").lower()
        if publish_status == "published":
            return Gate0CheckStatus.PASS, "Bot is published."
        return (
            Gate0CheckStatus.FAIL,
            "Your bot is not published. Publish it in XO Platform before submitting. "
            "Go to Deploy → Publish and select all components.",
        )

    def _check_web_channel(self, bot_data: dict[str, Any]) -> tuple[Gate0CheckStatus, str]:
        """Check channelInfos for a web/mobile SDK channel entry. WARN not FAIL."""
        channels = bot_data.get("channelInfos", [])
        channel_types = {c.get("type", "").lower() for c in channels}
        # Kore.ai uses 'websdkapp' or 'rtm' for the Web/Mobile Client channel
        web_types = {"websdkapp", "rtm", "websdk", "web"}
        if channel_types & web_types:
            return Gate0CheckStatus.PASS, "Web channel is enabled."
        return (
            Gate0CheckStatus.WARN,
            "Web channel not enabled on your bot. Tasks requiring web driver evaluation "
            "cannot be tested. All webhook tasks and FAQ will be evaluated normally. "
            "To enable: XO Platform → Channels → Web/Mobile Client → Enable.",
        )

    def _check_webhook_version(self, url: str) -> tuple[Gate0CheckStatus, str]:
        """Parse webhook URL path for /v2/ segment."""
        if "/v2/" in url:
            return Gate0CheckStatus.PASS, "Webhook V2 confirmed."
        if "/v1/" in url:
            return (
                Gate0CheckStatus.FAIL,
                "V2 webhook channel required. Your webhook URL appears to be V1 (missing '/v2/'). "
                "In XO Platform: Channels → Webhook → Version 2.0 → Enable. "
                "V1 is not supported — it does not send endOfTask signals or structured template "
                "responses that GovernIQ depends on.",
            )
        return (
            Gate0CheckStatus.WARN,
            "Webhook URL does not contain a version segment ('/v2/'). "
            "Confirm Webhook V2 is enabled in XO Platform.",
        )

    async def _check_webhook_reachability(self, url: str) -> tuple[Gate0CheckStatus, str]:
        """HEAD probe to the webhook URL to confirm it's reachable."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.head(url)
            if response.status_code == 404:
                return Gate0CheckStatus.FAIL, "Webhook URL not found. Is the webhook channel enabled?"
            return Gate0CheckStatus.PASS, f"Webhook reachable (HTTP {response.status_code})."
        except httpx.ConnectError:
            return Gate0CheckStatus.FAIL, "Cannot reach webhook URL. Check the URL and try again."
        except httpx.TimeoutException:
            return Gate0CheckStatus.FAIL, "Webhook URL timed out. Is the bot published?"

    async def _check_backend_api(self, url: str) -> tuple[Gate0CheckStatus, str]:
        """GET probe to the backend API URL — any response = reachable."""
        if not url:
            return Gate0CheckStatus.SKIP, "No backend API URL provided."
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.get(url)
            return Gate0CheckStatus.PASS, "Backend API reachable."
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            return Gate0CheckStatus.FAIL, f"Cannot reach backend API URL: {e}"
```

- [ ] **Step 3.5: Run tests — verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_gate0.py -v
```

Expected: all tests PASS

- [ ] **Step 3.6: Commit**

```bash
git add src/governiq/core/gate0.py src/governiq/webhook/kore_api.py tests/test_gate0.py
git commit -m "feat: add Gate0Checker with Bot Details API sub-checks and V2 webhook version check"
```

---

## Task 4: Wire Gate 0 into the Engine + FAILED_CONNECTIVITY

**Files:**
- Modify: `src/governiq/core/engine.py`

### What it does

Before Gate 1 (CBM parse), call `Gate0Checker.run()`. If any check fails, raise an exception with the failure messages so the caller can transition the submission to `FAILED_CONNECTIVITY` or return a `422` with actionable feedback to the candidate.

The connectivity re-check (Challenge 22 from the architecture) also runs right before Gate 2 (webhook conversations) — if the bot went offline between submission and evaluation, catch it cleanly.

- [ ] **Step 4.1: Add Gate0 imports to engine.py**

At the top of `src/governiq/core/engine.py`, add:

```python
from .gate0 import Gate0Checker, Gate0CheckStatus, Gate0Result
```

- [ ] **Step 4.2: Add `gate0_result` attribute to EvaluationEngine**

In `__init__`, after `self.kore_api_client`:

```python
self.gate0_result: Gate0Result | None = None
```

- [ ] **Step 4.3: Add `run_gate0` method to EvaluationEngine**

```python
async def run_gate0(self) -> Gate0Result:
    """Run Gate 0 connectivity checks. Must be called before run_full_evaluation().

    Raises ValueError with actionable messages if any check fails.
    Stores result in self.gate0_result for downstream use (e.g. web channel skipping).
    """
    checker = Gate0Checker(
        webhook_url=self.manifest.webhook_url,
        bot_id=getattr(self.kore_credentials, "bot_id", ""),
        backend_api_url=self.manifest.mock_api_base_url,
        kore_api_client=self.kore_api_client,
    )
    result = await checker.run()
    self.gate0_result = result

    if not result.can_proceed:
        failed = [
            f"[{check}] {msg}"
            for check, status in result.checks.items()
            if status == Gate0CheckStatus.FAIL
            for msg in [result.messages.get(check, "")]
        ]
        raise ValueError(
            "Gate 0 failed — evaluation cannot start:\n" + "\n".join(failed)
        )
    return result
```

- [ ] **Step 4.4: Add connectivity re-check before Gate 2**

In `run_full_evaluation`, immediately before the webhook task loop (look for `# Step 6` or the `_run_webhook_pipeline` call), add:

```python
# Pre-Gate 2: re-check webhook connectivity (bot may have gone offline after submission)
try:
    async with httpx.AsyncClient(timeout=10.0) as _probe:
        probe_resp = await _probe.head(self.manifest.webhook_url)
    if probe_resp.status_code == 404:
        raise ValueError(
            "FAILED_CONNECTIVITY: Bot webhook returned 404. "
            "The bot may have been taken offline since submission. Candidate should resubmit."
        )
except (httpx.ConnectError, httpx.TimeoutException) as e:
    raise ValueError(
        f"FAILED_CONNECTIVITY: Bot webhook unreachable before Gate 2: {e}. "
        "Candidate should verify webhook is active and resubmit."
    )
```

Also add `import httpx` if not already at the top of `engine.py`.

- [ ] **Step 4.5: Run existing engine tests — no regressions**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py -k "engine or startup or scorecard" 2>&1 | tail -15
```

- [ ] **Step 4.6: Commit**

```bash
git add src/governiq/core/engine.py
git commit -m "feat: wire Gate0Checker into engine, add pre-Gate2 FAILED_CONNECTIVITY check"
```

---

## Task 5: FAQ Live Evaluation — Webhook Driver + Semantic Similarity

**Files:**
- Create: `src/governiq/webhook/faq_evaluator.py`
- Modify: `src/governiq/core/engine.py`
- Create: `tests/test_faq_evaluator.py`

### What it does

`FAQEvaluator` sends each `FAQTask.question` to the candidate's bot in an isolated webhook session (same driver as webhook tasks). The bot's response text is compared against `expected_answer` using a multilingual sentence-transformers model. Pass if cosine similarity ≥ `similarity_threshold`. Result stored as a `CheckResult` and `EvidenceCard`.

The model `paraphrase-multilingual-mpnet-base-v2` handles bot responses in any language regardless of what language `expected_answer` is written in. It is loaded once and reused across all FAQ tasks.

- [ ] **Step 5.1: Write the failing tests**

```python
# tests/test_faq_evaluator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from governiq.webhook.faq_evaluator import FAQEvaluator, FAQEvalResult
from governiq.core.manifest import FAQTask


def make_faq_task(threshold=0.75):
    return FAQTask(
        task_id="FAQ-HOURS",
        question="What are your opening hours?",
        expected_answer="The clinic is open from 9 AM to 5 PM, Monday to Saturday.",
        similarity_threshold=threshold,
    )


class TestFAQEvalResult:
    def test_pass_when_similarity_above_threshold(self):
        task = make_faq_task(threshold=0.75)
        result = FAQEvalResult(
            task_id="FAQ-HOURS",
            similarity=0.82,
            threshold=0.75,
            bot_response="We are open 9 to 5, Monday through Saturday.",
            expected_answer=task.expected_answer,
        )
        assert result.passed is True

    def test_fail_when_similarity_below_threshold(self):
        task = make_faq_task(threshold=0.80)
        result = FAQEvalResult(
            task_id="FAQ-HOURS",
            similarity=0.45,
            threshold=0.80,
            bot_response="Please contact our front desk.",
            expected_answer=task.expected_answer,
        )
        assert result.passed is False


class TestFAQEvaluatorSimilarity:
    """Unit tests for semantic similarity computation — no network calls."""

    def test_compute_similarity_identical_strings(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        # Load model directly for unit test
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "The clinic is open from 9 AM to 5 PM.",
            "The clinic is open from 9 AM to 5 PM.",
        )
        assert sim > 0.99

    def test_compute_similarity_paraphrase(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "We are open Monday to Saturday, 9 AM to 5 PM.",
            "The clinic is open from 9 AM to 5 PM, Monday to Saturday.",
        )
        assert sim > 0.75

    def test_compute_similarity_unrelated(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "Please contact our front desk.",
            "The clinic is open from 9 AM to 5 PM, Monday to Saturday.",
        )
        assert sim < 0.50


class TestFAQEvaluatorWebhook:
    """Integration tests — mock the webhook client."""

    @pytest.mark.asyncio
    async def test_evaluate_single_faq_pass(self):
        task = make_faq_task(threshold=0.70)

        mock_driver = AsyncMock()
        mock_driver.run_faq_turn = AsyncMock(
            return_value="We are open Monday to Saturday from 9 AM to 5 PM."
        )

        evaluator = FAQEvaluator(
            webhook_driver=mock_driver,
            submission_id="SUB-001",
        )

        # Patch the model to return high similarity
        with patch.object(evaluator, "_compute_similarity", return_value=0.85):
            result = await evaluator.evaluate_task(task)

        assert result.passed is True
        assert result.similarity == 0.85

    @pytest.mark.asyncio
    async def test_evaluate_single_faq_fail_generic_deflection(self):
        task = make_faq_task(threshold=0.70)

        mock_driver = AsyncMock()
        mock_driver.run_faq_turn = AsyncMock(
            return_value="Please contact our front desk for that information."
        )

        evaluator = FAQEvaluator(
            webhook_driver=mock_driver,
            submission_id="SUB-001",
        )

        with patch.object(evaluator, "_compute_similarity", return_value=0.22):
            result = await evaluator.evaluate_task(task)

        assert result.passed is False
        assert result.similarity == 0.22
```

- [ ] **Step 5.2: Run tests — verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_faq_evaluator.py -v 2>&1 | head -20
```

- [ ] **Step 5.3: Create `src/governiq/webhook/faq_evaluator.py`**

```python
"""FAQ Evaluator — live webhook FAQ evaluation via semantic similarity.

For each FAQTask in the manifest, sends the configured question to the
candidate's bot in an isolated webhook session, then scores the response
against the expected_answer using a multilingual sentence-transformers model.

Model: paraphrase-multilingual-mpnet-base-v2
  - Handles bot responses in any language
  - expected_answer is written in English; the model bridges language at runtime
  - Loaded once per FAQEvaluator instance, shared across all FAQ tasks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from sentence_transformers import SentenceTransformer

from ..core.manifest import FAQTask
from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"


@dataclass
class FAQEvalResult:
    task_id: str
    similarity: float
    threshold: float
    bot_response: str
    expected_answer: str

    @property
    def passed(self) -> bool:
        return self.similarity >= self.threshold

    def to_check_result(self) -> CheckResult:
        status = CheckStatus.PASS if self.passed else CheckStatus.FAIL
        return CheckResult(
            check_id=f"faq.{self.task_id}.semantic_similarity",
            task_id=self.task_id,
            pipeline="webhook",
            label=f"FAQ semantic similarity — {self.task_id}",
            status=status,
            details=(
                f"Similarity: {self.similarity:.2f} (threshold: {self.threshold:.2f}). "
                + ("PASS — response matches expected answer." if self.passed
                   else "FAIL — response does not match expected answer. "
                        "Check FAQ knowledge graph answer content.")
            ),
            evidence=f"Bot response: {self.bot_response!r}\nExpected: {self.expected_answer!r}",
            score=1.0 if self.passed else 0.0,
            weight=1.0,
        )

    def to_evidence_card(self) -> EvidenceCard:
        color = EvidenceCardColor.GREEN if self.passed else EvidenceCardColor.RED
        return EvidenceCard(
            card_id=f"faq.{self.task_id}.evidence",
            task_id=self.task_id,
            title=f"FAQ — {self.task_id}",
            content=(
                f"Similarity: {self.similarity:.2f} / {self.threshold:.2f} threshold\n"
                f"Bot response: {self.bot_response}\n"
                f"Expected: {self.expected_answer}"
            ),
            color=color,
            pipeline="webhook",
        )


class FAQEvaluator:
    """Runs live FAQ evaluation for all FAQ tasks in the manifest."""

    def __init__(
        self,
        webhook_driver: object,  # KoreWebhookClient — imported at call site to avoid circular
        submission_id: str,
        model_name: str = _MODEL_NAME,
    ):
        self._driver = webhook_driver
        self._submission_id = submission_id
        self._model: SentenceTransformer | None = None
        self._model_name = model_name

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading sentence-transformers model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _compute_similarity(self, text_a: str, text_b: str) -> float:
        """Cosine similarity between two strings using the multilingual model."""
        model = self._get_model()
        embeddings = model.encode([text_a, text_b], convert_to_numpy=True)
        # Cosine similarity: dot product of normalized vectors
        a = embeddings[0] / (np.linalg.norm(embeddings[0]) + 1e-9)
        b = embeddings[1] / (np.linalg.norm(embeddings[1]) + 1e-9)
        return float(np.dot(a, b))

    async def evaluate_task(self, task: FAQTask) -> FAQEvalResult:
        """Run a single FAQ question and score the response.

        Opens an isolated session (unique from.id per FAQ task), sends the
        question, collects the bot's response, computes similarity.
        """
        session_id = f"eval-{self._submission_id}-{task.task_id}"
        logger.info("FAQ evaluation: task=%s session=%s", task.task_id, session_id)

        # run_faq_turn: send question, get bot response text (single turn)
        bot_response = await self._driver.run_faq_turn(
            question=task.question,
            session_id=session_id,
        )

        similarity = self._compute_similarity(bot_response, task.expected_answer)
        logger.info(
            "FAQ %s: similarity=%.3f threshold=%.3f passed=%s",
            task.task_id, similarity, task.similarity_threshold,
            similarity >= task.similarity_threshold,
        )

        return FAQEvalResult(
            task_id=task.task_id,
            similarity=similarity,
            threshold=task.similarity_threshold,
            bot_response=bot_response,
            expected_answer=task.expected_answer,
        )

    async def evaluate_all(
        self, faq_tasks: list[FAQTask]
    ) -> list[FAQEvalResult]:
        """Evaluate all FAQ tasks sequentially. Returns one result per task."""
        results = []
        for task in faq_tasks:
            try:
                result = await self.evaluate_task(task)
            except Exception as e:
                logger.error("FAQ task %s failed: %s", task.task_id, e)
                result = FAQEvalResult(
                    task_id=task.task_id,
                    similarity=0.0,
                    threshold=task.similarity_threshold,
                    bot_response=f"[ERROR: {e}]",
                    expected_answer=task.expected_answer,
                )
            results.append(result)
        return results
```

- [ ] **Step 5.4: Add `run_faq_turn` to KoreWebhookClient**

In `src/governiq/webhook/driver.py`, find `KoreWebhookClient` and add:

```python
async def run_faq_turn(self, question: str, session_id: str) -> str:
    """Send a single FAQ question in an isolated session, return bot's text response.

    Resets session state via start_session() so each FAQ question gets its own
    from_id, then delegates to the existing send_message() interface.
    Does not use the LLM conversation driver.
    """
    from .message_normaliser import normalise_messages
    # start_session sets self._from_id = "eval-req-post-{session_id}"
    # and resets _kore_session_id so each FAQ turn is isolated
    await self.start_session(submission_id=session_id)
    messages = await self.send_message(question)
    texts, _ = normalise_messages(messages or [])
    return " ".join(t for t in texts if t and t != "[template message]").strip()
```

- [ ] **Step 5.5: Integrate FAQEvaluator into engine.run_full_evaluation**

In `src/governiq/core/engine.py`, after the webhook task loop (after `context.save`), add:

```python
# Step 6b: FAQ live evaluation (after webhook tasks complete)
if self.manifest.faq_tasks:
    logger.info("=== FAQ Live Evaluation (%d tasks) ===", len(self.manifest.faq_tasks))
    from ..webhook.faq_evaluator import FAQEvaluator
    faq_evaluator = FAQEvaluator(
        webhook_driver=self.webhook_client,
        submission_id=session_id,
    )
    faq_results = await faq_evaluator.evaluate_all(self.manifest.faq_tasks)

    faq_task_score = next(
        (ts for ts in scorecard.task_scores if ts.task_id == "faq"),
        None,
    )
    if not faq_task_score:
        from .scoring import TaskScore
        faq_task_score = TaskScore(task_id="faq", task_name="FAQs")
        scorecard.task_scores.append(faq_task_score)

    for result in faq_results:
        faq_task_score.webhook_checks.append(result.to_check_result())
        faq_task_score.evidence_cards.append(result.to_evidence_card())
```

- [ ] **Step 5.6: Run FAQ evaluator tests**

```bash
venv/Scripts/python -m pytest tests/test_faq_evaluator.py -v
```

Note: `TestFAQEvaluatorSimilarity` tests download the model on first run (~400 MB). Run with network access. They will be slow (model download + inference). Expected: all PASS.

- [ ] **Step 5.7: Run full test suite**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -10
```

- [ ] **Step 5.8: Commit**

```bash
git add src/governiq/webhook/faq_evaluator.py src/governiq/webhook/driver.py src/governiq/core/engine.py tests/test_faq_evaluator.py
git commit -m "feat: add FAQEvaluator with multilingual semantic similarity scoring"
```

---

## Task 6: Response Type Detector

**Files:**
- Create: `src/governiq/webhook/response_type_detector.py`
- Create: `tests/test_response_type_detector.py`

### What it does

Classifies each webhook `data[]` entry. Kore.ai V2 webhook responses carry structured payloads for buttons, inline forms, carousels, and external URLs alongside plain text. The detector determines which handler should process the response. Returns a `ResponseType` enum and extracts the structured payload.

- [ ] **Step 6.1: Write the failing tests**

```python
# tests/test_response_type_detector.py
import pytest
from governiq.webhook.response_type_detector import ResponseType, detect_response_type


class TestDetectResponseType:
    def test_plain_text(self):
        messages = [{"val": "How can I help you?"}]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.TEXT
        assert payload is None

    def test_buttons_template(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "quick_replies",
                "elements": [
                    {"title": "Book Appointment"},
                    {"title": "Cancel Appointment"},
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.BUTTONS
        assert payload is not None
        assert len(payload["elements"]) == 2

    def test_inline_form(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "form",
                "formDef": {
                    "name": "BookingForm",
                    "components": [
                        {"key": "patientName", "displayName": "Patient Name"},
                        {"key": "date", "displayName": "Date"},
                    ]
                }
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.INLINE_FORM
        assert payload is not None
        assert "formDef" in payload

    def test_carousel(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "carousel",
                "elements": [
                    {"title": "Option A", "subtitle": "Details A"},
                    {"title": "Option B", "subtitle": "Details B"},
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.CAROUSEL
        assert len(payload["elements"]) == 2

    def test_external_url(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "button",
                "elements": [
                    {"type": "web_url", "url": "https://form.example.com/book", "openInTab": True}
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.EXTERNAL_URL
        assert "https://" in payload["url"]

    def test_mixed_text_and_template_returns_template_type(self):
        # When both text and a template are in the response, the template takes precedence
        messages = [
            {"val": "Please fill out this form:"},
            {
                "type": "template",
                "payload": {
                    "template_type": "form",
                    "formDef": {"name": "F", "components": []}
                }
            }
        ]
        rtype, _ = detect_response_type(messages)
        assert rtype == ResponseType.INLINE_FORM

    def test_unknown_template_falls_back_to_text(self):
        messages = [{"type": "template", "payload": {"template_type": "unknown_future_type"}}]
        rtype, _ = detect_response_type(messages)
        assert rtype == ResponseType.TEXT
```

- [ ] **Step 6.2: Run tests — verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_response_type_detector.py -v 2>&1 | head -10
```

- [ ] **Step 6.3: Create `src/governiq/webhook/response_type_detector.py`**

```python
"""Response Type Detector — classify Kore.ai webhook data[] responses.

Kore.ai V2 webhook sends structured payloads for buttons, forms, carousels,
and URLs alongside plain text. This module detects the response type so the
correct handler can process it.

Response type hierarchy (first match wins):
  EXTERNAL_URL  — button with web_url type and openInTab: true
  INLINE_FORM   — template_type == "form"
  CAROUSEL      — template_type == "carousel"
  BUTTONS       — template_type == "quick_replies" or "buttons"
  TEXT          — everything else (including unknown template types)
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ResponseType(str, Enum):
    TEXT = "text"
    BUTTONS = "buttons"
    INLINE_FORM = "inline_form"
    CAROUSEL = "carousel"
    EXTERNAL_URL = "external_url"


def detect_response_type(
    messages: list[Any],
) -> tuple[ResponseType, dict[str, Any] | None]:
    """Classify a list of Kore.ai message objects from a single bot turn.

    Returns:
        (ResponseType, payload) where payload is the structured dict for
        non-text types, or None for TEXT.

    Template types take precedence over plain text in the same turn.
    Unknown template_type values fall back to TEXT.
    """
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") != "template":
            continue

        payload = msg.get("payload", {})
        template_type = payload.get("template_type", "")
        elements = payload.get("elements", [])

        # External URL — button element with web_url type
        if template_type in ("button", "quick_replies", "buttons"):
            for el in elements:
                if isinstance(el, dict) and el.get("type") == "web_url":
                    url = el.get("url", "")
                    if url:
                        return ResponseType.EXTERNAL_URL, {"url": url, "element": el}

        if template_type == "form":
            return ResponseType.INLINE_FORM, payload

        if template_type == "carousel":
            return ResponseType.CAROUSEL, payload

        if template_type in ("quick_replies", "buttons", "button"):
            return ResponseType.BUTTONS, payload

        # Unknown template type — fall through to TEXT
        return ResponseType.TEXT, None

    return ResponseType.TEXT, None
```

- [ ] **Step 6.4: Run tests — verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_response_type_detector.py -v
```

- [ ] **Step 6.5: Commit**

```bash
git add src/governiq/webhook/response_type_detector.py tests/test_response_type_detector.py
git commit -m "feat: add Response Type Detector for Kore.ai webhook data[] responses"
```

---

## Task 7: Semantic Field Mapper

**Files:**
- Create: `src/governiq/webhook/semantic_field_mapper.py`
- Modify: `src/governiq/webhook/driver.py`
- Create: `tests/test_semantic_field_mapper.py`

### What it does

When the Response Type Detector returns `BUTTONS`, `INLINE_FORM`, or `CAROUSEL`, the Semantic Field Mapper takes the structured payload and the current task's manifest entities, matches the persona's entity values to the structured UI, and produces the webhook response payload to send back. This handles rich UI on the webhook path — no browser required.

For buttons: find the button label that matches the manifest entity value (exact → contains → semantic fallback).
For forms: map form component labels to manifest entity keys using `uiMappingHints` + semantic fallback; build `formData` response.
For carousels: find the card whose title semantically matches the persona's entity value; return the selection.

- [ ] **Step 7.1: Write the failing tests**

```python
# tests/test_semantic_field_mapper.py
import pytest
from governiq.webhook.semantic_field_mapper import SemanticFieldMapper, MappingResult


class TestButtonMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_exact_match(self):
        buttons = [
            {"title": "Book Appointment"},
            {"title": "Cancel Appointment"},
            {"title": "View Appointment"},
        ]
        result = self.mapper.map_buttons(buttons, target_value="Cancel Appointment")
        assert result.matched_label == "Cancel Appointment"
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_contains_match(self):
        buttons = [
            {"title": "Book an Appointment"},
            {"title": "Cancel an Appointment"},
        ]
        result = self.mapper.map_buttons(buttons, target_value="Book")
        assert result.matched_label == "Book an Appointment"
        assert result.strategy == "contains"

    def test_no_match_returns_first(self):
        buttons = [{"title": "Option A"}, {"title": "Option B"}]
        result = self.mapper.map_buttons(buttons, target_value="Something Unrelated")
        # Falls back to first button with low confidence
        assert result.matched_label is not None
        assert result.confidence < 0.5

    def test_empty_buttons_raises(self):
        with pytest.raises(ValueError, match="No buttons"):
            self.mapper.map_buttons([], target_value="Anything")


class TestFormMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_label_hint_match(self):
        form_components = [
            {"key": "comp1", "displayName": "Patient Name"},
            {"key": "comp2", "displayName": "Appointment Date"},
        ]
        entity_map = {
            "patientName": {
                "value": "Rajesh Kumar",
                "label_hints": ["Patient Name", "Full Name"],
            },
            "date": {
                "value": "02-04-2026",
                "label_hints": ["Appointment Date", "Date"],
            },
        }
        result = self.mapper.map_form(form_components, entity_map)
        assert result["comp1"] == "Rajesh Kumar"
        assert result["comp2"] == "02-04-2026"

    def test_unmapped_component_returns_none(self):
        form_components = [{"key": "comp_unknown", "displayName": "Clinic Branch"}]
        entity_map = {
            "patientName": {"value": "Rajesh Kumar", "label_hints": ["Patient Name"]},
        }
        result = self.mapper.map_form(form_components, entity_map)
        assert result.get("comp_unknown") is None


class TestCarouselMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_semantic_match(self):
        cards = [
            {"title": "Option A — Category 1"},
            {"title": "Option B — Category 2"},
            {"title": "Option C — Category 3"},
        ]
        # "Category 2" should semantically match "Option B — Category 2"
        result = self.mapper.map_carousel(cards, target_value="Category 2", strategy="semantic")
        assert result.matched_label == "Option B — Category 2"
        assert result.strategy == "semantic"

    def test_exact_carousel_match(self):
        cards = [{"title": "Option A"}, {"title": "Option B"}]
        result = self.mapper.map_carousel(cards, target_value="Option A", strategy="exact")
        assert result.matched_label == "Option A"
        assert result.confidence == 1.0
```

- [ ] **Step 7.2: Run tests — verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_semantic_field_mapper.py -v 2>&1 | head -10
```

- [ ] **Step 7.3: Create `src/governiq/webhook/semantic_field_mapper.py`**

```python
"""Semantic Field Mapper — maps webhook UI payloads to manifest entity values.

Called by the Webhook Driver after the Response Type Detector identifies a
structured response (buttons, inline form, carousel). The mapper finds the
best match for the persona's entity value within the UI payload, and
returns what to send back to the bot.

No browser required — this operates entirely on the webhook JSON.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MappingResult:
    matched_label: str | None
    strategy: str   # "exact", "contains", "semantic", "fallback"
    confidence: float
    index: int = 0  # position in the list (for click/select payloads)


class SemanticFieldMapper:
    """Maps persona entity values to webhook UI element selections."""

    def __init__(self, similarity_threshold: float = 0.60):
        self._similarity_threshold = similarity_threshold
        self._model = None  # Loaded lazily (same sentence-transformers model)

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        return self._model

    def _semantic_best_match(
        self, target: str, candidates: list[str]
    ) -> tuple[int, float]:
        """Return (index, similarity) of the best semantic match."""
        import numpy as np
        model = self._get_model()
        all_texts = [target] + candidates
        embeddings = model.encode(all_texts, convert_to_numpy=True)
        target_emb = embeddings[0] / (np.linalg.norm(embeddings[0]) + 1e-9)
        best_idx, best_sim = 0, -1.0
        for i, emb in enumerate(embeddings[1:]):
            norm_emb = emb / (np.linalg.norm(emb) + 1e-9)
            sim = float(np.dot(target_emb, norm_emb))
            if sim > best_sim:
                best_sim = sim
                best_idx = i
        return best_idx, best_sim

    def map_buttons(
        self, buttons: list[dict[str, Any]], target_value: str
    ) -> MappingResult:
        """Find the button label best matching target_value.

        Strategy: exact → contains → semantic → fallback (first button).
        """
        if not buttons:
            raise ValueError("No buttons to map against.")

        labels = [b.get("title", "") for b in buttons]

        # Exact match
        for i, label in enumerate(labels):
            if label.lower() == target_value.lower():
                return MappingResult(matched_label=label, strategy="exact", confidence=1.0, index=i)

        # Contains match
        for i, label in enumerate(labels):
            if target_value.lower() in label.lower() or label.lower() in target_value.lower():
                return MappingResult(matched_label=label, strategy="contains", confidence=0.85, index=i)

        # Semantic match
        best_idx, best_sim = self._semantic_best_match(target_value, labels)
        if best_sim >= self._similarity_threshold:
            return MappingResult(
                matched_label=labels[best_idx],
                strategy="semantic",
                confidence=best_sim,
                index=best_idx,
            )

        # Fallback — return first with low confidence, log warning
        logger.warning(
            "Button mapping: no match for '%s' in %s — falling back to first button.",
            target_value, labels,
        )
        return MappingResult(matched_label=labels[0], strategy="fallback", confidence=0.0, index=0)

    def map_form(
        self,
        form_components: list[dict[str, Any]],
        entity_map: dict[str, dict[str, Any]],
    ) -> dict[str, str | None]:
        """Map form component keys to entity values.

        entity_map: { entityKey: {"value": "...", "label_hints": ["..."]} }
        Returns: { componentKey: value or None if unmapped }
        """
        result: dict[str, str | None] = {}
        comp_labels = [c.get("displayName", "") for c in form_components]
        comp_keys = [c.get("key", "") for c in form_components]

        for comp_key, comp_label in zip(comp_keys, comp_labels):
            matched_value = None
            for entity_key, entity_info in entity_map.items():
                hints = entity_info.get("label_hints", [])
                value = entity_info.get("value", "")
                # Check label hints (exact or contains)
                for hint in hints:
                    if hint.lower() == comp_label.lower() or hint.lower() in comp_label.lower():
                        matched_value = value
                        break
                if matched_value is not None:
                    break
            result[comp_key] = matched_value

        return result

    def map_carousel(
        self,
        cards: list[dict[str, Any]],
        target_value: str,
        strategy: str = "semantic",
    ) -> MappingResult:
        """Find the card best matching target_value.

        strategy: "exact" | "contains" | "semantic"
        """
        if not cards:
            raise ValueError("No carousel cards to map against.")

        titles = [c.get("title", "") for c in cards]

        if strategy == "exact":
            for i, title in enumerate(titles):
                if title.lower() == target_value.lower():
                    return MappingResult(matched_label=title, strategy="exact", confidence=1.0, index=i)

        if strategy in ("contains", "exact"):
            for i, title in enumerate(titles):
                if target_value.lower() in title.lower():
                    return MappingResult(matched_label=title, strategy="contains", confidence=0.85, index=i)

        # Semantic (default)
        best_idx, best_sim = self._semantic_best_match(target_value, titles)
        return MappingResult(
            matched_label=titles[best_idx],
            strategy="semantic",
            confidence=best_sim,
            index=best_idx,
        )
```

- [ ] **Step 7.4: Run tests**

```bash
venv/Scripts/python -m pytest tests/test_semantic_field_mapper.py -v
```

Note: Tests load the sentence-transformers model. First run downloads it (~400 MB). Expected: all PASS.

- [ ] **Step 7.5: Integrate into driver.py**

In `src/governiq/webhook/driver.py`, import the new modules and update the response handling in the conversation loop. Find where `normalise_messages` is called to get text, and after it, add a type-detection branch:

```python
from .response_type_detector import detect_response_type, ResponseType
from .semantic_field_mapper import SemanticFieldMapper

# In the turn loop, after getting messages from the webhook:
texts, raws = normalise_messages(messages or [])
response_type, structured_payload = detect_response_type(raws)

if response_type == ResponseType.TEXT:
    # Existing LLM Actor path — no change
    pass
elif response_type in (ResponseType.BUTTONS, ResponseType.CAROUSEL, ResponseType.INLINE_FORM):
    # Semantic Field Mapper path — no LLM needed for structured UI
    # Handled by the pattern executor via the structured payload
    pass
# EXTERNAL_URL is handled separately by pattern executors that check for it
```

The full integration into the pattern executor flow requires pattern-level changes that go beyond this task. The imports and detection call are wired here; patterns pick up `response_type` and `structured_payload` from the turn result in a follow-on task.

- [ ] **Step 7.6: Run full test suite**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -15
```

Expected: all passing

- [ ] **Step 7.7: Commit**

```bash
git add src/governiq/webhook/semantic_field_mapper.py src/governiq/webhook/driver.py tests/test_semantic_field_mapper.py
git commit -m "feat: add Semantic Field Mapper for webhook-served buttons, forms, and carousels"
```

---

## Task 8: Final Integration Check

**Files:** none new — verification only

- [ ] **Step 8.1: Run the full test suite one final time**

```bash
venv/Scripts/python -m pytest tests/ -v --ignore=tests/test_integration_real_bots.py 2>&1 | tail -20
```

Expected: all tests pass. Note the count of passing tests — verify it has grown from the start of this sprint.

- [ ] **Step 8.2: Verify new models load correctly from the medical manifest**

```python
# Quick smoke test — run from repo root with venv active
python -c "
import json
from governiq.core.manifest import Manifest, FAQTask, UIPolicy
from governiq.core.manifest_validator import validate_manifest

data = json.load(open('manifests/medical_appointment_basic.json'))
data['faq_tasks'] = [{
    'task_id': 'FAQ-HOURS',
    'question': 'What are your opening hours?',
    'expected_answer': 'Open 9 AM to 5 PM.',
    'similarity_threshold': 0.80
}]
m = Manifest(**data)
result = validate_manifest(m)
print('Manifest valid:', result.valid)
print('FAQ tasks:', [t.task_id for t in m.faq_tasks])
print('Task ui_policies:', [(t.task_id, t.ui_policy) for t in m.tasks[:2]])
"
```

Expected output:
```
Manifest valid: True
FAQ tasks: ['FAQ-HOURS']
Task ui_policies: [('task2_booking1', <UIPolicy.PREFER_WEBHOOK: 'prefer_webhook'>), ...]
```

- [ ] **Step 8.3: Verify Gate0Checker runs synchronously on a dead URL**

```python
import asyncio
from governiq.core.gate0 import Gate0Checker

async def test():
    checker = Gate0Checker(
        webhook_url="https://bots.kore.ai/chatbot/v2/fakeid",
        bot_id="st-fakeid",
        backend_api_url="",
    )
    result = await checker.run()
    print("can_proceed:", result.can_proceed)
    print("checks:", result.checks)

asyncio.run(test())
```

Expected: `can_proceed: False` (webhook unreachable + no kore_api_client → SKIP for bot details)

- [ ] **Step 8.4: Final commit**

```bash
git add .
git commit -m "chore: core pipeline improvements sprint complete — Gate0, FAQ semantic eval, Response Type Detector, Semantic Field Mapper"
```

---

## What comes next

**Plan 2 — Web Driver:** `KoreWebDriver` (Playwright + Kore.ai Web SDK), GovernIQ host page, JWT session token endpoint. Depends on this plan's `UIPolicy` enum and `uiPolicy` field on `TaskDefinition`.

**Plan 3 — Platform Assumption Workbench:** Pre-build API verification test suite covering Automation AI, Search AI, Quality AI, and Case Management APIs. A developer tool run before writing app code — verifies all Kore.ai API endpoints and Web SDK channel details in the target environment.
