"""Kore.ai JWT Token Generator — Creates JWT tokens for Kore.ai API authentication.

Kore.ai uses JWT tokens signed with the Client Secret to authenticate API calls.
The token contains the Bot ID and Client ID as claims.

Reference: https://developer.kore.ai/docs/bots/sdks/botkit-sdk-tutorial-agent-transfer/
"""

from __future__ import annotations

import hashlib
import hmac
import json
import base64
import time
import logging
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

    Args:
        credentials: The bot's Kore.ai credentials.
        expiry_seconds: Token expiry in seconds (default 5 minutes).

    Returns:
        Signed JWT token string.
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
        "iat": now,
        "exp": now + expiry_seconds,
        "iss": credentials.client_id,
        "appId": credentials.client_id,
    }

    # Encode header and payload
    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    # Create signature
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
    1. Generate JWT signed with Client Secret
    2. POST to /api/1.1/oAuth/token/jwtgrant with the JWT
    3. Receive a bearer access_token

    Returns:
        Bearer access token string.

    Raises:
        httpx.HTTPStatusError: If the token exchange fails.
    """
    jwt_token = generate_jwt_token(credentials)

    token_url = f"{credentials.platform_url}/api/1.1/oAuth/token/jwtgrant"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url,
            json={
                "assertion": jwt_token,
                "botInfo": {
                    "chatBot": credentials.bot_id,
                    "taskBotId": credentials.bot_id,
                },
            },
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

    access_token = data.get("authorization", {}).get("accessToken", "")
    if not access_token:
        # Some Kore.ai versions return it differently
        access_token = data.get("access_token", "")
    if not access_token:
        raise ValueError(f"No access token in response: {data}")

    logger.info("Kore.ai bearer token obtained (expires in 5 min)")
    return access_token


async def test_webhook_with_jwt(
    credentials: KoreCredentials,
    webhook_url: str,
    test_message: str = "Hi",
) -> dict[str, Any]:
    """Test a webhook connection using JWT authentication.

    Generates a JWT, gets a bearer token, and sends a test message.

    Returns:
        Dict with success status, response, and token info.
    """
    result: dict[str, Any] = {
        "success": False,
        "jwt_generated": False,
        "bearer_obtained": False,
        "webhook_responded": False,
        "response": None,
        "error": None,
    }

    try:
        # Step 1: Generate JWT
        jwt_token = generate_jwt_token(credentials)
        result["jwt_generated"] = True

        # Step 2: Get bearer token
        bearer_token = await get_kore_bearer_token(credentials)
        result["bearer_obtained"] = True

        # Step 3: Test webhook
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                webhook_url,
                json={
                    "message": {"type": "text", "val": test_message},
                    "from": {"id": "jwt-test-driver"},
                },
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                },
            )
            response.raise_for_status()
            result["webhook_responded"] = True
            result["response"] = response.json()
            result["success"] = True

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        result["error"] = str(e)

    return result
