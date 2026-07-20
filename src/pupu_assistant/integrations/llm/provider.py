from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from typing import Any, Protocol

from pupu_assistant.integrations.llm.models import AgentTurn, ChatMessage

ToolDefinition = Mapping[str, Any]


class LLMProvider(Protocol):
    async def run_agent(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
        allowed_tools: Set[str],
    ) -> AgentTurn: ...
