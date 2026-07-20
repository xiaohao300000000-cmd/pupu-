from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class FunctionToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: str

    def as_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    reasoning_content: str | None = None
    tool_calls: tuple[FunctionToolCall, ...] = ()
    tool_call_id: str | None = None

    def as_api_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.reasoning_content is not None:
            payload["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            payload["tool_calls"] = [call.as_api_dict() for call in self.tool_calls]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


class AgentTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str | None
    reasoning_content: str | None = None
    tool_calls: tuple[FunctionToolCall, ...] = ()
