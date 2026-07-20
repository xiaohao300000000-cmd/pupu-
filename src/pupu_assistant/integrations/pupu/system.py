from typing import Protocol

from pupu_assistant.integrations.pupu.models import (
    PupuResponse,
    SignatureRequirement,
)


class PupuRequester(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        **kwargs: object,
    ) -> PupuResponse: ...


class PupuSystemService:
    def __init__(self, client: PupuRequester) -> None:
        self._client = client

    async def get_server_time(self) -> int:
        response = await self._client.request(
            "GET",
            "/client/base/data",
            signature_requirement=SignatureRequirement.PUBLIC,
        )
        data = response.data
        server_time = data.get("server_time") if isinstance(data, dict) else None
        if not isinstance(server_time, int) or server_time <= 0:
            raise ValueError("Pupu response did not contain a valid server time")
        return server_time
