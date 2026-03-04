"""Conversation Driver — LLM-powered bot conversation automation.

Startup: LLM is primary for conversation start. manifest.conversationStarter
is the fallback. There is no 'LLM fallback' — the manifest IS the fallback.

classifyBotIntent operates in four states:
  - entity_request: bot is asking for information
  - confirmation_request: bot is asking for yes/no confirmation
  - information: bot is providing information
  - error: bot returned an error
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.manifest import TaskDefinition

logger = logging.getLogger(__name__)


class LLMConversationDriver:
    """LLM-powered conversation driver for webhook interactions.

    Supports multiple API formats:
    - "openai": OpenAI, Azure, Gemini, Mistral (all OpenAI-compatible)
    - "anthropic": Anthropic Claude (Messages API)

    Falls back to rule-based heuristics when LLM is unavailable.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-haiku-4-5-20251001",
        base_url: str = "https://api.anthropic.com/v1",
        temperature: float = 0.3,
        api_format: str = "anthropic",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.api_format = api_format  # "openai" or "anthropic"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            headers: dict[str, str] = {}
            if self.api_format == "anthropic":
                headers["x-api-key"] = self.api_key
                headers["anthropic-version"] = "2023-06-01"
                headers["content-type"] = "application/json"
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def _llm_call(self, system_prompt: str, user_prompt: str) -> str | None:
        """Make an LLM API call. Supports both Anthropic and OpenAI formats."""
        if not self.api_key:
            return None
        try:
            client = await self._get_client()

            if self.api_format == "anthropic":
                response = await client.post(
                    "/messages",
                    json={
                        "model": self.model,
                        "max_tokens": 256,
                        "system": system_prompt,
                        "messages": [
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.temperature,
                    },
                )
                response.raise_for_status()
                data = response.json()
                # Anthropic Messages API format
                content = data.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "").strip()
                return None
            else:
                # OpenAI-compatible format (OpenAI, Azure, Gemini, Mistral)
                response = await client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": self.temperature,
                        "max_tokens": 256,
                    },
                )
                response.raise_for_status()
                data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("LLM call failed, falling back to rules: %s", e)
            return None

    # ---------------------------------------------------------------------------
    # ConversationDriver protocol methods
    # ---------------------------------------------------------------------------

    async def generate_opening(self, task: TaskDefinition) -> str:
        """Generate an opening message for the task. LLM primary, manifest fallback."""
        system = (
            "You are simulating a user interacting with a chatbot. "
            "Generate a natural opening message to start a conversation "
            "about the following task. Keep it brief and natural — 1-2 sentences."
        )
        user = f"Task: {task.task_name}. Dialog: {task.dialog_name}."

        llm_result = await self._llm_call(system, user)
        if llm_result:
            return llm_result

        # Manifest fallback
        if task.conversation_starter:
            return task.conversation_starter
        return "Hi"

    async def generate_entity_injection(
        self, entity_key: str, value: str, semantic_hint: str, bot_message: str
    ) -> str:
        """Generate a natural message that provides an entity value."""
        system = (
            "You are simulating a user responding to a chatbot. The bot asked "
            "for information. Respond naturally with the given value. "
            "Keep your response brief — just provide the information requested. "
            "Do NOT add extra questions or commentary."
        )
        user = (
            f"Bot said: \"{bot_message}\"\n"
            f"You need to provide: {semantic_hint}\n"
            f"Value to provide: {value}"
        )

        llm_result = await self._llm_call(system, user)
        if llm_result:
            return llm_result

        # Rule-based fallback
        return str(value)

    async def generate_amendment(self, template: str, amended_value: str) -> str:
        """Generate an amendment utterance from the template."""
        result = template.replace("{amended_value}", amended_value)

        system = (
            "Rephrase this amendment request to sound natural and conversational. "
            "Keep the meaning identical. One sentence."
        )
        llm_result = await self._llm_call(system, result)
        return llm_result or result

    async def generate_confirmation(self, bot_message: str) -> str:
        """Generate a confirmation response."""
        system = (
            "You are a user confirming something a chatbot said. "
            "Respond with a brief, natural confirmation. "
            "Example: 'Yes, that's correct' or 'Yes, please proceed'."
        )
        llm_result = await self._llm_call(system, f'Bot said: "{bot_message}"')
        return llm_result or "Yes, that's correct."

    async def classify_bot_intent(self, bot_message: str) -> str:
        """Classify the bot's message into one of four states.

        Returns one of:
          - 'entity_request': bot is asking for information
          - 'confirmation_request': bot is asking for yes/no confirmation
          - 'information': bot is providing information
          - 'error': bot returned an error
        """
        system = (
            "Classify the following chatbot message into exactly one category:\n"
            "- entity_request: the bot is asking the user for information (name, date, number, etc)\n"
            "- confirmation_request: the bot is asking for yes/no confirmation\n"
            "- information: the bot is providing information or results\n"
            "- error: the bot returned an error message\n\n"
            "Respond with ONLY the category name, nothing else."
        )
        llm_result = await self._llm_call(system, f'Bot message: "{bot_message}"')

        if llm_result:
            result = llm_result.lower().strip()
            if result in ("entity_request", "confirmation_request", "information", "error"):
                return result

        # Rule-based fallback (four-state classification)
        return self._classify_rule_based(bot_message)

    def _classify_rule_based(self, message: str) -> str:
        """Rule-based intent classification fallback."""
        msg = message.lower()

        # Error indicators
        error_keywords = {"error", "sorry, i", "i'm sorry", "cannot", "unable to", "failed"}
        if any(kw in msg for kw in error_keywords):
            return "error"

        # Confirmation indicators
        confirm_keywords = {
            "confirm", "is that correct", "shall i proceed", "would you like to",
            "do you want", "is this correct", "please confirm", "yes or no",
        }
        if any(kw in msg for kw in confirm_keywords):
            return "confirmation_request"

        # Entity request indicators
        request_keywords = {
            "please provide", "what is your", "what's your", "enter your",
            "please enter", "could you", "can you provide", "may i know",
            "what would you like", "please share", "kindly provide",
            "tell me your", "?",
        }
        if any(kw in msg for kw in request_keywords):
            return "entity_request"

        # Default: information
        return "information"

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class KoreWebhookClient:
    """Client for communicating with a Kore.ai bot.

    Supports two modes:
    1. **BotMessages API** (preferred): Uses bearer token from JWT auth flow.
       Sends messages via POST /api/1.1/botmessages and polls for responses.
    2. **Direct Webhook**: Sends messages to the webhook URL (fallback for
       non-Kore bots or when JWT auth is not available).

    The bearer_token and kore_credentials params enable BotMessages API mode.
    """

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 30.0,
        bearer_token: str = "",
        kore_credentials: Any = None,
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.bearer_token = bearer_token
        self.kore_credentials = kore_credentials
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._user_id: str = ""

    @property
    def uses_bot_api(self) -> bool:
        """True if using BotMessages API (JWT auth), False if direct webhook."""
        return bool(self.bearer_token and self.kore_credentials)

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def start_session(self) -> None:
        """Start a new conversation session with the bot."""
        import uuid
        self._session_id = str(uuid.uuid4())
        self._user_id = f"eval-{uuid.uuid4().hex[:8]}"

    async def send_message(self, message: str) -> str:
        """Send a message to the bot and return the response.

        Uses BotMessages API when bearer token is available,
        falls back to direct webhook otherwise.
        """
        if self.uses_bot_api:
            return await self._send_via_bot_api(message)
        return await self._send_via_webhook(message)

    async def _send_via_bot_api(self, message: str) -> str:
        """Send message via Kore.ai BotMessages API (authenticated)."""
        import asyncio

        client = await self._get_client()
        creds = self.kore_credentials
        bot_name = getattr(creds, 'bot_name', '') or creds.bot_id
        platform_url = creds.platform_url

        # Send message
        send_url = f"{platform_url}/api/1.1/botmessages"
        payload = {
            "message": {"type": "text", "val": message},
            "from": {"id": self._user_id or "eval-driver"},
            "botInfo": {
                "chatBot": bot_name,
                "taskBotId": creds.bot_id,
            },
        }

        try:
            response = await client.post(
                send_url,
                json=payload,
                headers={
                    "Authorization": f"bearer {self.bearer_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            send_data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("BotMessages API send failed: HTTP %s — %s",
                         e.response.status_code, e.response.text[:200])
            # Fall back to webhook if BotMessages API fails
            if self.webhook_url:
                logger.info("Falling back to direct webhook")
                return await self._send_via_webhook(message)
            raise

        # Poll for bot response
        poll_url = f"{platform_url}/api/1.1/botmessages"
        params = {"botId": creds.bot_id, "userId": self._user_id or "eval-driver"}

        for attempt in range(5):
            await asyncio.sleep(1.5 + attempt * 0.5)
            try:
                response = await client.get(
                    poll_url,
                    params=params,
                    headers={
                        "Authorization": f"bearer {self.bearer_token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

                messages = data if isinstance(data, list) else data.get("messages", [])
                if messages:
                    return self._extract_bot_text(messages)
            except Exception as e:
                logger.debug("Poll attempt %d: %s", attempt + 1, e)

        # If polling returns nothing, return the send response
        return self._extract_bot_text(send_data)

    async def _send_via_webhook(self, message: str) -> str:
        """Send message via direct webhook URL (unauthenticated or pre-auth'd URL)."""
        client = await self._get_client()

        payload = {
            "session": {"new": self._session_id is None},
            "message": {"type": "text", "val": message},
            "from": {"id": self._session_id or "eval-driver"},
        }

        headers: dict[str, str] = {}
        if self.bearer_token:
            headers["Authorization"] = f"bearer {self.bearer_token}"

        try:
            response = await client.post(
                self.webhook_url, json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return self._extract_bot_text(data)
        except httpx.HTTPStatusError as e:
            logger.error("Webhook HTTP error: %s", e)
            raise
        except Exception as e:
            logger.error("Webhook error: %s", e)
            raise

    def _extract_bot_text(self, data: Any) -> str:
        """Extract human-readable text from various Kore.ai response formats."""
        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            if "text" in data:
                return data["text"]
            if "data" in data and isinstance(data["data"], list):
                texts = [
                    item.get("val", "") or item.get("text", "")
                    for item in data["data"] if isinstance(item, dict)
                ]
                return " ".join(t for t in texts if t)
            if "message" in data:
                msg = data["message"]
                if isinstance(msg, dict):
                    return msg.get("val", "") or msg.get("text", "") or str(msg)
                return str(msg)
            if "val" in data:
                return data["val"]

        if isinstance(data, list) and data:
            parts = []
            for item in data:
                if isinstance(item, dict):
                    parts.append(
                        item.get("text", "")
                        or item.get("val", "")
                        or item.get("message", {}).get("val", "")
                        or str(item)
                    )
                else:
                    parts.append(str(item))
            return " ".join(parts)

        return str(data)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
