"""Kore.ai Public API Client — Fetches analytics and bot info via JWT auth.

Leverages Kore.ai public APIs to get:
- Bot analytics (usage, conversation counts, etc.)
- Bot details and configuration
- NLP training data insights
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from .jwt_auth import KoreCredentials, get_kore_bearer_token

logger = logging.getLogger(__name__)

# Token refresh margin — re-fetch 5 minutes before expiry
_TOKEN_EXPIRY_SECONDS = 3600
_TOKEN_REFRESH_MARGIN = 300.0


class KoreAPIClient:
    """Client for Kore.ai public APIs authenticated via JWT."""

    def __init__(self, credentials: KoreCredentials):
        self.credentials = credentials
        self._bearer_token: str | None = None
        self._token_obtained_at: float = 0.0

    async def _ensure_token(self) -> str:
        """Get or refresh the bearer token (re-fetches near expiry)."""
        if self._bearer_token:
            elapsed = time.time() - self._token_obtained_at
            if elapsed < (_TOKEN_EXPIRY_SECONDS - _TOKEN_REFRESH_MARGIN):
                return self._bearer_token
            logger.info("Admin bearer token near expiry (%.0fs old), refreshing", elapsed)

        self._bearer_token = await get_kore_bearer_token(self.credentials)
        self._token_obtained_at = time.time()
        return self._bearer_token

    async def _api_get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        """Make an authenticated GET request to the Kore.ai API."""
        token = await self._ensure_token()
        url = f"{self.credentials.platform_url}{endpoint}"
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

    async def _api_post(self, endpoint: str, payload: dict | None = None) -> dict[str, Any]:
        """Make an authenticated POST request."""
        token = await self._ensure_token()
        url = f"{self.credentials.platform_url}{endpoint}"
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

    # -----------------------------------------------------------------------
    # Bot Info
    # -----------------------------------------------------------------------

    async def get_bot_details(self) -> dict[str, Any]:
        """Fetch bot details (name, description, settings, channels, etc.)."""
        endpoint = f"/api/public/bot/{self.credentials.bot_id}"
        try:
            return await self._api_get(endpoint)
        except Exception as e:
            logger.error("Failed to get bot details: %s", e)
            return {"error": str(e)}

    # -----------------------------------------------------------------------
    # Analytics
    # -----------------------------------------------------------------------

    async def get_analytics_summary(
        self, days_back: int = 30
    ) -> dict[str, Any]:
        """Fetch bot analytics summary for the past N days.

        Returns conversation counts, user counts, success/failure rates.
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days_back)

        endpoint = f"/api/public/bot/{self.credentials.bot_id}/getAnalytics"
        payload = {
            "type": "summary",
            "startDate": start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endDate": end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        try:
            return await self._api_post(endpoint, payload)
        except Exception as e:
            logger.error("Failed to get analytics: %s", e)
            return {"error": str(e)}

    async def get_conversation_history(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Fetch recent conversation history from the bot."""
        endpoint = f"/api/public/bot/{self.credentials.bot_id}/conversationHistory"
        params = {"limit": limit, "offset": offset}
        try:
            return await self._api_get(endpoint, params)
        except Exception as e:
            logger.error("Failed to get conversation history: %s", e)
            return {"error": str(e)}

    async def get_intent_detection_stats(self) -> dict[str, Any]:
        """Fetch NLP intent detection statistics."""
        endpoint = f"/api/public/bot/{self.credentials.bot_id}/intentDetection"
        try:
            return await self._api_get(endpoint)
        except Exception as e:
            logger.error("Failed to get intent stats: %s", e)
            return {"error": str(e)}

    async def get_all_insights(self, days_back: int = 30) -> dict[str, Any]:
        """Fetch all available insights in one call.

        Returns a combined dict with bot details, analytics, and intent stats.
        """
        results: dict[str, Any] = {}

        try:
            results["bot_details"] = await self.get_bot_details()
        except Exception as e:
            results["bot_details"] = {"error": str(e)}

        try:
            results["analytics"] = await self.get_analytics_summary(days_back)
        except Exception as e:
            results["analytics"] = {"error": str(e)}

        try:
            results["intent_stats"] = await self.get_intent_detection_stats()
        except Exception as e:
            results["intent_stats"] = {"error": str(e)}

        return results
