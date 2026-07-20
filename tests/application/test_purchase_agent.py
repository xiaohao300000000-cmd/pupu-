import json

import pytest
from pydantic import BaseModel, ConfigDict

from pupu_assistant.application.orchestrator import (
    PurchaseAgent,
    ToolRoundLimitExceeded,
)
from pupu_assistant.application.tool_registry import (
    ToolNotAllowed,
    ToolRegistry,
    ToolRisk,
    ToolSpec,
)
from pupu_assistant.integrations.llm.models import AgentTurn, FunctionToolCall


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SequenceProvider:
    def __init__(self, turns: list[AgentTurn]) -> None:
        self.turns = turns
        self.calls: list[tuple[list, list, set[str]]] = []

    async def run_agent(self, *, messages, tools, allowed_tools):
        self.calls.append((list(messages), list(tools), set(allowed_tools)))
        return self.turns.pop(0)


@pytest.mark.asyncio
async def test_agent_executes_validated_read_tool_and_returns_final_answer() -> None:
    executions: list[str] = []

    async def search(arguments: SearchArguments):
        executions.append(arguments.query)
        return {"products": [{"id": "p1", "name": "Fresh milk"}]}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search_products",
            description="Search real catalog products",
            arguments_model=SearchArguments,
            handler=search,
            risk=ToolRisk.READ_ONLY,
        )
    )
    provider = SequenceProvider(
        [
            AgentTurn(
                content="",
                reasoning_content="catalog required",
                tool_calls=(
                    FunctionToolCall(
                        id="call-1",
                        name="search_products",
                        arguments='{ "query": "milk" }',
                    ),
                ),
            ),
            AgentTurn(content="Found fresh milk", tool_calls=()),
        ]
    )
    agent = PurchaseAgent(provider=provider, tools=registry, max_tool_rounds=3)

    result = await agent.run(
        "Buy milk",
        allowed_tools={"search_products"},
    )

    assert result.content == "Found fresh milk"
    assert executions == ["milk"]
    second_messages = provider.calls[1][0]
    assistant = second_messages[-2]
    tool_result = second_messages[-1]
    assert assistant.reasoning_content == "catalog required"
    assert assistant.tool_calls[0].id == "call-1"
    assert tool_result.role == "tool"
    assert json.loads(tool_result.content)["products"][0]["id"] == "p1"


@pytest.mark.asyncio
async def test_agent_rejects_model_attempt_to_call_unapproved_write_tool() -> None:
    async def write(arguments: EmptyArguments):
        del arguments
        return {"written": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="execute_cart_sync",
            description="Write the real cart",
            arguments_model=EmptyArguments,
            handler=write,
            risk=ToolRisk.REAL_WRITE,
        )
    )
    provider = SequenceProvider(
        [
            AgentTurn(
                content="",
                tool_calls=(
                    FunctionToolCall(
                        id="call-write",
                        name="execute_cart_sync",
                        arguments="{}",
                    ),
                ),
            )
        ]
    )
    agent = PurchaseAgent(provider=provider, tools=registry, max_tool_rounds=2)

    with pytest.raises(ToolNotAllowed):
        await agent.run("write now", allowed_tools=set())

    assert provider.calls[0][1] == []


@pytest.mark.asyncio
async def test_agent_stops_an_unbounded_tool_loop() -> None:
    async def search(arguments: SearchArguments):
        return {"query": arguments.query}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search_products",
            description="Search products",
            arguments_model=SearchArguments,
            handler=search,
            risk=ToolRisk.READ_ONLY,
        )
    )
    repeated = AgentTurn(
        content="",
        tool_calls=(
            FunctionToolCall(
                id="call-loop",
                name="search_products",
                arguments='{"query":"milk"}',
            ),
        ),
    )
    provider = SequenceProvider([repeated, repeated, repeated])
    agent = PurchaseAgent(provider=provider, tools=registry, max_tool_rounds=2)

    with pytest.raises(ToolRoundLimitExceeded):
        await agent.run("keep looking", allowed_tools={"search_products"})

    assert len(provider.calls) == 3
