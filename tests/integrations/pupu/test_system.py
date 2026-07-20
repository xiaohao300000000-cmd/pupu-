from typing import Any

import pytest

from pupu_assistant.integrations.pupu.models import (
    PupuResponse,
    SignatureRequirement,
)
from pupu_assistant.integrations.pupu.system import PupuSystemService


class RecordingClient:
    def __init__(self, response: PupuResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> PupuResponse:
        self.calls.append((method, path, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_server_time_uses_signature_first_http_client() -> None:
    client = RecordingClient(
        PupuResponse(
            status_code=200,
            errcode=0,
            data={"server_time": 1_753_036_200_123},
            payload={"errcode": 0, "data": {"server_time": 1_753_036_200_123}},
        )
    )

    server_time = await PupuSystemService(client).get_server_time()

    assert server_time == 1_753_036_200_123
    assert client.calls == [
        (
            "GET",
            "/client/base/data",
            {"signature_requirement": SignatureRequirement.PUBLIC},
        )
    ]


@pytest.mark.asyncio
async def test_server_time_rejects_missing_or_invalid_value() -> None:
    client = RecordingClient(
        PupuResponse(
            status_code=200,
            errcode=0,
            data={},
            payload={"errcode": 0, "data": {}},
        )
    )

    with pytest.raises(ValueError, match="server time"):
        await PupuSystemService(client).get_server_time()
