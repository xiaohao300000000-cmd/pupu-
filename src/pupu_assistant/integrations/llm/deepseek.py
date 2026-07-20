from __future__ import annotations

from collections.abc import Sequence, Set
from typing import Any

import httpx

from pupu_assistant.integrations.llm.models import (
    AgentTurn,
    ChatMessage,
    FunctionToolCall,
)
from pupu_assistant.integrations.llm.provider import ToolDefinition


class DeepSeekError(RuntimeError):
    """Base class for safe DeepSeek integration errors."""


class DeepSeekConfigurationError(DeepSeekError):
    pass


class DeepSeekRateLimitError(DeepSeekError):
    pass


class DeepSeekTransportError(DeepSeekError):
    pass


class DeepSeekResponseError(DeepSeekError):
    pass


class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise DeepSeekConfigurationError("DeepSeek API key is required")
        if not model:
            raise DeepSeekConfigurationError("DeepSeek model is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )

    async def run_agent(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
        allowed_tools: Set[str],
    ) -> AgentTurn:
        exposed_tools = [
            dict(tool)
            for tool in tools
            if self._tool_name(tool) in allowed_tools
        ]
        request_body: dict[str, Any] = {
            "model": self._model,
            "messages": [message.as_api_dict() for message in messages],
        }
        if exposed_tools:
            request_body["tools"] = exposed_tools

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json=request_body,
            )
        except httpx.TimeoutException as error:
            raise DeepSeekTransportError("DeepSeek request timed out") from error
        except httpx.TransportError as error:
            raise DeepSeekTransportError("DeepSeek network request failed") from error

        if response.status_code == 429:
            raise DeepSeekRateLimitError("DeepSeek rate limit exceeded")
        if not 200 <= response.status_code < 300:
            raise DeepSeekResponseError(
                f"DeepSeek returned HTTP status {response.status_code}"
            )
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            tool_calls = tuple(
                FunctionToolCall(
                    id=call["id"],
                    name=call["function"]["name"],
                    arguments=call["function"]["arguments"],
                )
                for call in message.get("tool_calls", [])
            )
            return AgentTurn(
                content=message.get("content"),
                reasoning_content=message.get("reasoning_content"),
                tool_calls=tool_calls,
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise DeepSeekResponseError("DeepSeek returned an invalid response") from error

    @staticmethod
    def _tool_name(tool: ToolDefinition) -> str | None:
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            return name if isinstance(name, str) else None
        return None

    async def aclose(self) -> None:
        await self._client.aclose()
