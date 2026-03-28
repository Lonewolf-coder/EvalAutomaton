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

        # Check 6: V2 webhook version (fast, no network)
        status, msg = self._check_webhook_version(self.webhook_url)
        result.checks["webhook_version"] = status
        result.messages["webhook_version"] = msg
        if status == Gate0CheckStatus.FAIL:
            return result  # No point checking reachability if URL is wrong

        # Check 5: Backend API reachability
        status, msg = await self._check_backend_api(self.backend_api_url)
        result.checks["backend_api"] = status
        result.messages["backend_api"] = msg

        # Check 1: Webhook reachability (HEAD probe)
        status, msg = await self._check_webhook_reachability(self.webhook_url)
        result.checks["webhook_reachability"] = status
        result.messages["webhook_reachability"] = msg

        # Checks 2, 3, 4: Bot Details API — single call, three sub-checks
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
            result.checks["bot_published"] = Gate0CheckStatus.SKIP
            result.checks["web_channel"] = Gate0CheckStatus.SKIP
            return
        except Exception as e:
            result.checks["bot_credentials"] = Gate0CheckStatus.FAIL
            result.messages["bot_credentials"] = f"Bot Details API unreachable: {e}"
            result.checks["bot_published"] = Gate0CheckStatus.SKIP
            result.checks["web_channel"] = Gate0CheckStatus.SKIP
            return

        result.checks["bot_credentials"] = Gate0CheckStatus.PASS
        result.messages["bot_credentials"] = "Admin credentials valid."

        status, msg = self._check_publish_status(bot_data)
        result.checks["bot_published"] = status
        result.messages["bot_published"] = msg

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
                "In XO Platform: Channels → Webhook → Version 2.0 → Enable.",
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
        except httpx.RequestError as e:
            return Gate0CheckStatus.FAIL, f"Webhook URL error: {e}"

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
        except httpx.RequestError as e:
            return Gate0CheckStatus.FAIL, f"Backend API error: {e}"
