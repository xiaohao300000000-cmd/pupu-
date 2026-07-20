from __future__ import annotations

import json
from dataclasses import dataclass

from pupu_assistant.application.tool_registry import ToolRegistry
from pupu_assistant.integrations.llm.models import ChatMessage
from pupu_assistant.integrations.llm.provider import LLMProvider


class PurchaseAgentError(RuntimeError):
    pass


class EmptyModelResponse(PurchaseAgentError):
    pass


class ToolRoundLimitExceeded(PurchaseAgentError):
    pass


@dataclass(frozen=True)
class AgentResult:
    content: str
    tool_rounds: int


SYSTEM_PROMPT = """You are a grocery purchase planner. Use only the tools exposed to you.
Never invent platform product IDs, prices, stock, or cart results. You may prepare a cart plan,
but you cannot write a real cart unless a separately verified state explicitly exposes that tool.
Ask one concise clarification question when required."""


class PurchaseAgent:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: ToolRegistry,
        max_tool_rounds: int,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be at least one")
        self._provider = provider
        self._tools = tools
        self._max_tool_rounds = max_tool_rounds
        self._system_prompt = system_prompt

    async def run(self, user_message: str, *, allowed_tools: set[str]) -> AgentResult:
        messages = [
            ChatMessage(role="system", content=self._system_prompt),
            ChatMessage(role="user", content=user_message),
        ]
        tool_rounds = 0

        while True:
            tools_for_turn = (
                self._tools.definitions(allowed_tools)
                if tool_rounds < self._max_tool_rounds
                else []
            )
            allowed_for_turn = (
                allowed_tools if tool_rounds < self._max_tool_rounds else set()
            )
            turn = await self._provider.run_agent(
                messages=messages,
                tools=tools_for_turn,
                allowed_tools=allowed_for_turn,
            )
            if not turn.tool_calls:
                if not turn.content or not turn.content.strip():
                    raise EmptyModelResponse("Model returned neither content nor tool calls")
                return AgentResult(content=turn.content, tool_rounds=tool_rounds)
            if tool_rounds >= self._max_tool_rounds:
                raise ToolRoundLimitExceeded("Model exceeded the tool-call round limit")

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=turn.content,
                    reasoning_content=turn.reasoning_content,
                    tool_calls=turn.tool_calls,
                )
            )
            for call in turn.tool_calls:
                result = await self._tools.execute(
                    call.name,
                    call.arguments,
                    allowed_tools=allowed_tools,
                )
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=json.dumps(
                            result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        tool_call_id=call.id,
                    )
                )
            tool_rounds += 1
