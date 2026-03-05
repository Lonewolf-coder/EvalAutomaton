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
import uuid
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
                content = data.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "").strip()
                return None
            else:
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
        """Classify the bot's message into one of four states."""
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

        return self._classify_rule_based(bot_message)

    def _classify_rule_based(self, message: str) -> str:
        """Rule-based intent classification fallback."""
        msg = message.lower()

        error_keywords = {"error", "sorry, i", "i'm sorry", "cannot", "unable to", "failed"}
        if any(kw in msg for kw in error_keywords):
            return "error"

        confirm_keywords = {
            "confirm", "is that correct", "shall i proceed", "would you like to",
            "do you want", "is this correct", "please confirm", "yes or no",
        }
        if any(kw in msg for kw in confirm_keywords):
            return "confirmation_request"

        request_keywords = {
            "please provide", "what is your", "what's your", "enter your",
            "please enter", "could you", "can you provide", "may i know",
            "what would you like", "please share", "kindly provide",
            "tell me your", "?",
        }
        if any(kw in msg for kw in request_keywords):
            return "entity_request"

        return "information"

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class KoreWebhookClient:
    """Client for Kore.ai bot webhook conversations.

    Implements the actual Kore.ai webhook protocol:
    - JWT (app-scope) is used directly as bearer token in Authorization header
    - First message sends session.new = true
    - Subsequent messages send session.id = <koreSessionId> from first response
    - Response format: {data: [{val: "..."}], sessionId, endOfTask, completedTaskName}
    - Timeout: 15s per request with 1 retry on 504

    The from.id acts as the session identifier on our side:
        eval-req-post-<submissionId>
    """

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 15.0,
        bearer_token: str = "",
        kore_credentials: Any = None,
    ):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.kore_credentials = kore_credentials
        self._client: httpx.AsyncClient | None = None
        self._jwt_token: str = ""
        self._from_id: str = ""
        self._kore_session_id: str | None = None
        self._is_new_session: bool = True
        self._last_end_of_task: bool = False
        self._last_completed_task: str = ""

        # Generate app-scope JWT for webhook auth (used directly as bearer)
        if kore_credentials:
            from .jwt_auth import generate_jwt_token
            self._jwt_token = generate_jwt_token(kore_credentials, scope="app")
        elif bearer_token:
            self._jwt_token = bearer_token

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def start_session(self, submission_id: str = "") -> None:
        """Start a new conversation session."""
        sub_id = submission_id or uuid.uuid4().hex[:12]
        self._from_id = f"eval-req-post-{sub_id}"
        self._kore_session_id = None
        self._is_new_session = True

    async def send_message(self, message: str) -> str:
        """Send a message to the bot webhook and return the response text.

        Implements the exact Kore.ai webhook protocol:
        - First call: session.new = true
        - Subsequent: session.id = <pinned koreSessionId>
        - Authorization: bearer <JWT> (app-scope, not exchanged)
        """
        client = await self._get_client()

        if not self._from_id:
            await self.start_session()

        # Build the Kore.ai webhook payload
        payload: dict[str, Any] = {
            "message": {"type": "text", "val": message},
            "from": {
                "id": self._from_id,
                "userInfo": {"firstName": "Agentic", "lastName": "Framework"},
            },
        }

        if self.kore_credentials:
            payload["to"] = {"id": self.kore_credentials.bot_id}

        # Session: new on first call, pinned session ID after
        if self._is_new_session:
            payload["session"] = {"new": True}
        elif self._kore_session_id:
            payload["session"] = {"id": self._kore_session_id}

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._jwt_token:
            headers["Authorization"] = f"bearer {self._jwt_token}"

        try:
            response = await client.post(
                self.webhook_url, json=payload, headers=headers
            )
            # Retry once on 504 gateway timeout
            if response.status_code == 504:
                logger.warning("504 on webhook, retrying once...")
                response = await client.post(
                    self.webhook_url, json=payload, headers=headers
                )
            response.raise_for_status()
            data = response.json()

            # Pin the session ID from the first response
            if self._is_new_session and isinstance(data, dict):
                session_id = data.get("sessionId") or data.get("session_id")
                if session_id:
                    self._kore_session_id = session_id
                    logger.info("Kore session pinned: %s", session_id)
                self._is_new_session = False

            return self._extract_bot_text(data)

        except httpx.HTTPStatusError as e:
            logger.error("Webhook HTTP %s: %s", e.response.status_code, e.response.text[:200])
            raise
        except Exception as e:
            logger.error("Webhook error: %s", e)
            raise

    @property
    def last_end_of_task(self) -> bool:
        """Whether the last response indicated end of task."""
        return self._last_end_of_task

    @property
    def last_completed_task(self) -> str:
        """The task name from the last endOfTask response."""
        return self._last_completed_task

    def _extract_bot_text(self, data: Any) -> str:
        """Extract human-readable text from the Kore.ai webhook response.

        Expected format:
        {
            data: [{val: "text1"}, {val: "text2"}],
            sessionId: "...",
            endOfTask: true/false,
            endReason: "fulfilled_event",
            completedTaskName: "BookFlight"
        }
        """
        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            # Track task completion signals
            self._last_end_of_task = data.get("endOfTask", False)
            self._last_completed_task = data.get("completedTaskName", "")

            # Primary: data[] array (standard Kore.ai webhook format)
            if "data" in data and isinstance(data["data"], list):
                texts = []
                for item in data["data"]:
                    if isinstance(item, dict):
                        val = item.get("val", "") or item.get("text", "")
                        if val:
                            texts.append(val)
                    elif isinstance(item, str):
                        texts.append(item)
                if texts:
                    return "\n".join(texts)

            if "text" in data:
                return data["text"]
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
                    parts.append(item.get("val", "") or item.get("text", "") or str(item))
                else:
                    parts.append(str(item))
            return "\n".join(p for p in parts if p)

        return str(data)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
