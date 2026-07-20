import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import httpx

from pupu_assistant.integrations.pupu.errors import (
    PupuBusinessError,
    PupuHttpStatusError,
    PupuNetworkError,
    PupuResponseDecodeError,
    PupuTimeoutError,
    PupuTlsError,
    SignaturePolicyViolation,
)
from pupu_assistant.integrations.pupu.models import (
    PupuRequestContext,
    PupuResponse,
    SignatureMode,
    SignatureRequirement,
)
from pupu_assistant.integrations.pupu.signature import PupuSignatureService

JsonBody = Mapping[str, object] | Sequence[object]


class PupuHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        signature_service: PupuSignatureService,
        app_version: str,
        os_type: str,
        http_client: httpx.AsyncClient | None = None,
        timestamp_ms: Callable[[], int],
        max_read_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        device_id: str | None = None,
        user_id: str | None = None,
        su_id: str | None = None,
        store_id: str | None = None,
        place_id: str | None = None,
        city_zip: str | None = None,
    ) -> None:
        if max_read_attempts < 1:
            raise ValueError("max_read_attempts must be at least one")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        self._base_url = base_url.rstrip("/")
        self._signature_service = signature_service
        self._app_version = app_version
        self._os_type = os_type
        self._http_client = http_client or httpx.AsyncClient()
        self._timestamp_ms = timestamp_ms
        self._max_read_attempts = max_read_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep
        self._identity = {
            "device_id": device_id,
            "user_id": user_id,
            "su_id": su_id,
            "store_id": store_id,
            "place_id": place_id,
            "city_zip": city_zip,
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Sequence[tuple[str, str]] = (),
        json_body: JsonBody | None = None,
        headers: Mapping[str, str] | None = None,
        signature_requirement: SignatureRequirement,
    ) -> PupuResponse:
        body = (
            json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            if json_body is not None
            else None
        )
        context = PupuRequestContext(
            method=method,
            path=path,
            query=tuple(query),
            body=body,
            timestamp_ms=self._timestamp_ms(),
            app_version=self._app_version,
            os_type=self._os_type,
            existing_headers=dict(headers or {}),
            **self._identity,
        )
        signed = self._signature_service.sign(context)
        if (
            signature_requirement is SignatureRequirement.PROTECTED
            and signed.signature_mode is not SignatureMode.SEAL_SIGN
        ):
            raise SignaturePolicyViolation(
                "Protected Pupu request did not receive a verified signature"
            )

        response = await self._send_with_retry(method=context.method, signed=signed)
        if not 200 <= response.status_code < 300:
            raise PupuHttpStatusError(
                f"Pupu returned HTTP status {response.status_code}"
            )

        try:
            payload: Any = response.json()
        except ValueError as error:
            raise PupuResponseDecodeError("Pupu returned invalid JSON") from error

        errcode = payload.get("errcode") if isinstance(payload, dict) else None
        if errcode not in (None, 0, "0"):
            raise PupuBusinessError(f"Pupu rejected the request with errcode={errcode}")

        data = payload.get("data") if isinstance(payload, dict) else payload
        return PupuResponse(
            status_code=response.status_code,
            errcode=errcode,
            data=data,
            payload=payload,
        )

    async def _send_with_retry(self, *, method: str, signed: Any) -> httpx.Response:
        attempts = self._max_read_attempts if method in {"GET", "HEAD"} else 1
        for attempt in range(1, attempts + 1):
            try:
                return await self._http_client.request(
                    method,
                    f"{self._base_url}{signed.path}",
                    params=signed.query,
                    content=signed.body,
                    headers=signed.headers,
                )
            except httpx.TimeoutException as error:
                if attempt < attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                raise PupuTimeoutError("Pupu request timed out") from error
            except httpx.TransportError as error:
                if attempt < attempts:
                    await self._sleep(self._retry_delay(attempt))
                    continue
                message = str(error).lower()
                if "tls" in message or "ssl" in message:
                    raise PupuTlsError("Pupu TLS negotiation failed") from error
                raise PupuNetworkError("Pupu network request failed") from error
        raise AssertionError("unreachable")

    def _retry_delay(self, failed_attempt: int) -> float:
        return min(self._retry_backoff_seconds * 2 ** (failed_attempt - 1), 5.0)

    async def aclose(self) -> None:
        await self._http_client.aclose()
