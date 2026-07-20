import httpx
import pytest

from pupu_assistant.integrations.llm.deepseek import (
    DeepSeekProvider,
    DeepSeekRateLimitError,
)
from pupu_assistant.integrations.llm.models import ChatMessage


@pytest.mark.asyncio
async def test_deepseek_uses_configured_api_and_preserves_tool_reasoning() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "need current catalog",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_products",
                                        "arguments": '{"query":"milk"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(
        api_key="secret-key",
        base_url="https://deepseek.example.test",
        model="configured-model",
        http_client=client,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_products",
                "description": "Search current products",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_cart_sync",
                "description": "Write cart",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    turn = await provider.run_agent(
        messages=[ChatMessage(role="user", content="buy milk")],
        tools=tools,
        allowed_tools={"search_products"},
    )
    await client.aclose()

    assert len(observed) == 1
    assert observed[0].url == "https://deepseek.example.test/chat/completions"
    assert observed[0].headers["authorization"] == "Bearer secret-key"
    request_body = __import__("json").loads(observed[0].content)
    assert request_body["model"] == "configured-model"
    assert [tool["function"]["name"] for tool in request_body["tools"]] == [
        "search_products"
    ]
    assert turn.reasoning_content == "need current catalog"
    assert turn.tool_calls[0].name == "search_products"
    assert turn.tool_calls[0].arguments == '{"query":"milk"}'


@pytest.mark.asyncio
async def test_deepseek_classifies_rate_limit_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(
        api_key="secret-key",
        base_url="https://deepseek.example.test",
        model="configured-model",
        http_client=client,
    )

    with pytest.raises(DeepSeekRateLimitError) as raised:
        await provider.run_agent(
            messages=[ChatMessage(role="user", content="hello")],
            tools=[],
            allowed_tools=set(),
        )
    await client.aclose()

    assert "secret-key" not in str(raised.value)
