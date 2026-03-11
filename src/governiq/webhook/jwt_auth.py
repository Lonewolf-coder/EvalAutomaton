"""Kore.ai JWT Token Generator — Creates JWT tokens for webhook authentication.

Two distinct JWT scopes:
  1. **App scope** (for webhook calls): Used as `bearer <JWT>` header directly
     on webhook POST calls. Claims: {appId, sub, scope:"app", iat, exp}
  2. **Admin scope** (for public APIs): Exchanged via /oAuth/token/jwtgrant
     for a bearer access_token. Claims: {appId, sub, scope:"admin", iat, exp}

The JWT is signed HS256 with the candidate's Client Secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import base64
import time
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class KoreCredentials:
    """Kore.ai platform credentials for a bot."""
    bot_id: str
    client_id: str
    client_secret: str
    bot_name: str = ""
    account_id: str = ""
    platform_url: str = "https://bots.kore.ai"

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors = []
        if not self.bot_id:
            errors.append("Bot ID is required")
        if not self.client_id:
            errors.append("Client ID is required")
        if not self.client_secret:
            errors.append("Client Secret is required")
        return errors


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def generate_jwt_token(
    credentials: KoreCredentials,
    scope: str = "app",
    expiry_seconds: int = 3600,
) -> str:
    """Generate a JWT token for Kore.ai authentication.

    Args:
        credentials: Bot credentials.
        scope: "app" for webhook calls (direct bearer), "admin" for API token exchange.
        expiry_seconds: Token lifetime (default 1 hour).

    Payload matches the actual Kore.ai jwtService format:
        {appId, sub, scope, iat}  (exp is added via expiry)
    """
    now = int(time.time())

    header = {"alg": "HS256", "typ": "JWT"}

    payload = {
        "appId": credentials.client_id,
        "sub": credentials.client_id,
        "scope": scope,
        "iat": now,
        "exp": now + expiry_seconds,
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        credentials.client_secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


async def get_kore_bearer_token(
    credentials: KoreCredentials,
) -> str:
    """Exchange an admin-scoped JWT for a Kore.ai bearer token.

    This is used for Kore.ai Public APIs (analytics, bot details, NLP insights).
    Webhook calls use the app-scope JWT directly — no exchange needed.

    Flow:
        1. Generate JWT with scope="admin"
        2. POST to /api/1.1/oAuth/token/jwtgrant
        3. Receive bearer access_token
    """
    jwt_token = generate_jwt_token(credentials, scope="admin")
    token_url = f"{credentials.platform_url}/api/1.1/oAuth/token/jwtgrant"
    bot_name = credentials.bot_name or credentials.bot_id

    logger.info("Requesting admin bearer token from %s", token_url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url,
            json={
                "assertion": jwt_token,
                "botInfo": {
                    "chatBot": bot_name,
                    "taskBotId": credentials.bot_id,
                },
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            logger.error(
                "JWT grant failed: HTTP %s — %s",
                response.status_code, response.text[:500],
            )
            response.raise_for_status()

        data = response.json()

    access_token = (
        data.get("authorization", {}).get("accessToken", "")
        or data.get("authorization", {}).get("token", "")
        or data.get("access_token", "")
        or data.get("accessToken", "")
    )
    if not access_token:
        raise ValueError(
            f"No access token in response. Keys: {list(data.keys())}. "
            f"Response: {json.dumps(data)[:300]}"
        )

    logger.info("Kore.ai admin bearer token obtained successfully")
    return access_token


async def test_webhook_with_jwt(
    credentials: KoreCredentials,
    webhook_url: str,
    test_message: str = "Hi",
) -> dict[str, Any]:
    """Test a webhook connection using JWT authentication.

    Generates an app-scope JWT and sends it directly as bearer token
    to the webhook URL (the actual Kore.ai webhook auth flow).
    """
    result: dict[str, Any] = {
        "success": False,
        "jwt_generated": False,
        "webhook_responded": False,
        "response": None,
        "error": None,
    }

    try:
        # Generate app-scope JWT (used directly as bearer — no exchange)
        jwt_token = generate_jwt_token(credentials, scope="app")
        result["jwt_generated"] = True
        logger.info("App-scope JWT generated for client_id=%s", credentials.client_id)

        # Build the Kore.ai webhook payload
        session_from_id = f"eval-req-post-{uuid.uuid4().hex[:12]}"
        payload = {
            "message": {"type": "text", "val": test_message},
            "from": {
                "id": session_from_id,
                "userInfo": {"firstName": "Agentic", "lastName": "Framework"},
            },
            "to": {"id": credentials.bot_id},
            "session": {"new": True},
        }

        import asyncio

        request_headers = {
            "Authorization": f"bearer {jwt_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                webhook_url, json=payload, headers=request_headers,
            )
            # Retry once on 504 gateway timeout
            if response.status_code == 504:
                logger.warning("504 on first attempt, retrying...")
                response = await client.post(
                    webhook_url, json=payload, headers=request_headers,
                )
            # Retry on 401 with 5s backoff (cold-start JWT recognition lag)
            if response.status_code == 401:
                for retry in range(2):
                    wait = 5.0 * (2 ** retry)
                    logger.warning(
                        "401 on webhook test, retrying in %.1fs (%d/2)...",
                        wait, retry + 1,
                    )
                    await asyncio.sleep(wait)
                    response = await client.post(
                        webhook_url, json=payload, headers=request_headers,
                    )
                    if response.status_code != 401:
                        break
            response.raise_for_status()
            result["webhook_responded"] = True
            result["response"] = response.json()
            result["success"] = True

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        logger.error("Webhook test failed: %s", result["error"])
    except Exception as e:
        result["error"] = str(e)
        logger.error("Webhook test failed: %s", e)

    return result
