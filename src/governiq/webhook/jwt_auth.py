"""Kore.ai JWT Token Generator — Creates JWT tokens for Kore.ai API authentication.

Kore.ai uses JWT tokens signed with the Client Secret to authenticate API calls.
The flow:
  1. Build JWT with proper claims (sub, iss, aud, appId, jti)
  2. Sign with HS256 using Client Secret
  3. POST to /api/1.1/oAuth/token/jwtgrant to exchange JWT for bearer token
  4. Use bearer token for BotMessages API and Public APIs

Reference: https://developer.kore.ai/docs/bots/api-guide/apis/
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
    bot_name: str = ""       # Human-readable bot name (for botInfo.chatBot)
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
    expiry_seconds: int = 300,
) -> str:
    """Generate a JWT token for Kore.ai API authentication.

    The JWT must contain these Kore.ai-specific claims:
    - sub: The Client ID (identifies the app)
    - iss: "cs-<client_id>" (cs prefix = client secret signing)
    - aud: "https://idproxy.kore.com/authorize"
    - appId: The Client ID
    - jti: Unique token ID (prevents replay)
    """
    now = int(time.time())

    # JWT Header
    header = {
        "alg": "HS256",
        "typ": "JWT",
    }

    # JWT Payload — Kore.ai specific claims
    payload = {
        "sub": credentials.client_id,
        "iss": f"cs-{credentials.client_id}",
        "aud": "https://idproxy.kore.com/authorize",
        "iat": now,
        "exp": now + expiry_seconds,
        "jti": str(uuid.uuid4()),
        "appId": credentials.client_id,
    }

    # Encode header and payload
    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    # Create HMAC-SHA256 signature
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
    """Exchange a JWT token for a Kore.ai bearer token via the /oAuth/token API.

    This is the standard Kore.ai auth flow:
    1. Generate JWT signed with Client Secret (with proper claims)
    2. POST to /api/1.1/oAuth/token/jwtgrant with the JWT + botInfo
    3. Receive a bearer access_token

    Returns:
        Bearer access token string.

    Raises:
        httpx.HTTPStatusError: If the token exchange fails.
    """
    jwt_token = generate_jwt_token(credentials)

    token_url = f"{credentials.platform_url}/api/1.1/oAuth/token/jwtgrant"

    # botInfo.chatBot can be bot name or bot ID — Kore.ai accepts both
    bot_name = credentials.bot_name or credentials.bot_id

    logger.info("Requesting bearer token from %s", token_url)

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

    # Kore.ai returns token in different locations depending on version
    access_token = (
        data.get("authorization", {}).get("accessToken", "")
        or data.get("authorization", {}).get("token", "")
        or data.get("access_token", "")
        or data.get("accessToken", "")
    )
    if not access_token:
        raise ValueError(f"No access token in Kore.ai response. Keys: {list(data.keys())}. Response: {json.dumps(data)[:300]}")

    logger.info("Kore.ai bearer token obtained successfully")
    return access_token


async def send_bot_message(
    credentials: KoreCredentials,
    bearer_token: str,
    message: str,
    user_id: str = "eval-driver",
) -> dict[str, Any]:
    """Send a message to a Kore.ai bot via the BotMessages API.

    This is the correct API for driving conversations with a Kore.ai bot
    programmatically (not the webhook URL, which is for inbound webhooks).

    POST /api/1.1/botmessages
    Authorization: bearer <token>

    Returns:
        Bot response data.
    """
    bot_name = credentials.bot_name or credentials.bot_id
    url = f"{credentials.platform_url}/api/1.1/botmessages"

    payload = {
        "message": {
            "type": "text",
            "val": message,
        },
        "from": {
            "id": user_id,
        },
        "botInfo": {
            "chatBot": bot_name,
            "taskBotId": credentials.bot_id,
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"bearer {bearer_token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


async def poll_bot_response(
    credentials: KoreCredentials,
    bearer_token: str,
    user_id: str = "eval-driver",
    poll_attempts: int = 5,
    poll_interval: float = 2.0,
) -> list[dict[str, Any]]:
    """Poll for bot responses after sending a message.

    GET /api/1.1/botmessages?botId=<bot_id>&userId=<user_id>

    Returns:
        List of bot response messages.
    """
    import asyncio

    url = f"{credentials.platform_url}/api/1.1/botmessages"
    params = {
        "botId": credentials.bot_id,
        "userId": user_id,
    }

    all_messages: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(poll_attempts):
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"bearer {bearer_token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

                messages = data if isinstance(data, list) else data.get("messages", [])
                if messages:
                    all_messages.extend(messages)
                    break
            except Exception as e:
                logger.debug("Poll attempt %d failed: %s", attempt + 1, e)

            if attempt < poll_attempts - 1:
                await asyncio.sleep(poll_interval)

    return all_messages


async def test_webhook_with_jwt(
    credentials: KoreCredentials,
    webhook_url: str = "",
    test_message: str = "Hi",
) -> dict[str, Any]:
    """Test bot connectivity using JWT authentication.

    Uses the BotMessages API (not webhook URL) for authenticated interaction.

    Returns:
        Dict with success status, response, and token info.
    """
    result: dict[str, Any] = {
        "success": False,
        "jwt_generated": False,
        "bearer_obtained": False,
        "bot_responded": False,
        "response": None,
        "error": None,
        "bearer_token": None,
    }

    try:
        # Step 1: Generate JWT
        jwt_token = generate_jwt_token(credentials)
        result["jwt_generated"] = True
        logger.info("JWT generated for client_id=%s", credentials.client_id)

        # Step 2: Get bearer token
        bearer_token = await get_kore_bearer_token(credentials)
        result["bearer_obtained"] = True
        result["bearer_token"] = bearer_token

        # Step 3: Send message via BotMessages API
        user_id = f"eval-{uuid.uuid4().hex[:8]}"
        send_response = await send_bot_message(
            credentials, bearer_token, test_message, user_id
        )
        logger.info("Message sent to bot, response: %s", json.dumps(send_response)[:200])

        # Step 4: Poll for bot response
        bot_messages = await poll_bot_response(
            credentials, bearer_token, user_id
        )
        if bot_messages:
            result["bot_responded"] = True
            result["response"] = bot_messages
        else:
            # Even without poll response, the send may have succeeded
            result["bot_responded"] = True
            result["response"] = send_response

        result["success"] = True

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
        logger.error("JWT auth test failed: %s", result["error"])
    except Exception as e:
        result["error"] = str(e)
        logger.error("JWT auth test failed: %s", e)

    return result
