from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python


class ToolRegistryError(RuntimeError):
    pass


class DuplicateTool(ToolRegistryError):
    pass


class UnknownTool(ToolRegistryError):
    pass


class ToolNotAllowed(ToolRegistryError):
    pass


class ToolArgumentsInvalid(ToolRegistryError):
    pass


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    ASSISTANT_CART = "assistant_cart"
    PREPARE_WRITE = "prepare_write"
    REAL_WRITE = "real_write"


ToolHandler = Callable[[BaseModel], Awaitable[Any] | Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: ToolHandler
    risk: ToolRisk

    def as_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise DuplicateTool(f"Tool is already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self, allowed_tools: Iterable[str]) -> list[dict[str, Any]]:
        allowed = set(allowed_tools)
        return [
            tool.as_definition()
            for name, tool in self._tools.items()
            if name in allowed
        ]

    async def execute(
        self,
        name: str,
        raw_arguments: str,
        *,
        allowed_tools: set[str],
    ) -> Any:
        if name not in allowed_tools:
            raise ToolNotAllowed(f"Tool is not allowed in the current state: {name}")
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownTool(f"Tool is not registered: {name}")
        try:
            decoded = json.loads(raw_arguments)
            arguments = tool.arguments_model.model_validate(decoded)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            raise ToolArgumentsInvalid(f"Invalid arguments for tool: {name}") from error

        result = tool.handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        return to_jsonable_python(result)
