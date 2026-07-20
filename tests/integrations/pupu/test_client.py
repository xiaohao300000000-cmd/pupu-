import json
from collections.abc import Callable

import httpx
import pytest

from pupu_assistant.integrations.pupu.client import PupuHttpClient
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
    SignatureMode,
    SignatureRequirement,
    SignedPupuRequest,
)
from pupu_assistant.integrations.pupu.signature import ProtectedSignatureUnavailable


class SpySignatureService:
    def __init__(
        self,
        transform: Callable[[PupuRequestContext], SignedPupuRequest],
    ) -> None:
        self.transform = transform
        self.calls: list[PupuRequestContext] = []

    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        self.calls.append(request)
        return self.transform(request)


def signed_from(
    request: PupuRequestContext,
    *,
    mode: SignatureMode = SignatureMode.NONE,
) -> SignedPupuRequest:
    return SignedPupuRequest(
        path=request.path,
        query=request.query,
        body=request.body,
        headers={name.lower(): value for name, value in request.existing_headers.items()},
        signature_mode=mode,
        metadata={"test": "true"},
    )


def make_client(
    signer: SpySignatureService,
    transport: httpx.AsyncBaseTransport,
    *,
    max_read_attempts: int = 1,
) -> PupuHttpClient:
    return PupuHttpClient(
        base_url="https://j1.pupuapi.com",
        signature_service=signer,
        app_version="6.4.5",
        os_type="Android",
        http_client=httpx.AsyncClient(transport=transport),
        timestamp_ms=lambda: 1_753_036_200_000,
        max_read_attempts=max_read_attempts,
    )


@pytest.mark.asyncio
async def test_client_signs_once_and_sends_only_signed_request() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"errcode": 0, "data": {"ok": True}})

    def transform(request: PupuRequestContext) -> SignedPupuRequest:
        return SignedPupuRequest(
            path="/normalized",
            query=(("signed_query", "yes"),),
            body=b'{"signed":true}',
            headers={"x-signed": "yes"},
            signature_mode=SignatureMode.SEAL_SIGN,
            metadata={"test": "true"},
        )

    signer = SpySignatureService(transform)
    client = make_client(signer, httpx.MockTransport(handler))

    response = await client.request(
        "post",
        "/original",
        query=(("original", "no"),),
        json_body={"original": True},
        headers={"X-Original": "no"},
        signature_requirement=SignatureRequirement.PROTECTED,
    )
    await client.aclose()

    assert len(signer.calls) == 1
    assert signer.calls[0].method == "POST"
    assert signer.calls[0].body == b'{"original":true}'
    assert len(observed) == 1
    assert observed[0].url.path == "/normalized"
    assert dict(observed[0].url.params) == {"signed_query": "yes"}
    assert observed[0].headers["x-signed"] == "yes"
    assert "x-original" not in observed[0].headers
    assert observed[0].content == b'{"signed":true}'
    assert response.data == {"ok": True}


@pytest.mark.asyncio
async def test_signing_failure_prevents_network_io() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"errcode": 0})

    def fail(request: PupuRequestContext) -> SignedPupuRequest:
        del request
        raise ProtectedSignatureUnavailable("unavailable")

    signer = SpySignatureService(fail)
    client = make_client(signer, httpx.MockTransport(handler))

    with pytest.raises(ProtectedSignatureUnavailable):
        await client.request(
            "GET",
            "/client/cart",
            signature_requirement=SignatureRequirement.PROTECTED,
        )
    await client.aclose()

    assert requests == 0


@pytest.mark.asyncio
async def test_protected_request_rejects_none_signature_before_network() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"errcode": 0})

    signer = SpySignatureService(signed_from)
    client = make_client(signer, httpx.MockTransport(handler))

    with pytest.raises(SignaturePolicyViolation):
        await client.request(
            "GET",
            "/client/cart",
            signature_requirement=SignatureRequirement.PROTECTED,
        )
    await client.aclose()

    assert requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ReadTimeout("slow"), PupuTimeoutError),
        (httpx.ConnectError("TLS handshake failed"), PupuTlsError),
        (httpx.ConnectError("connection reset"), PupuNetworkError),
    ],
)
async def test_transport_errors_are_classified(
    raised: httpx.HTTPError,
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raised.request = request
        raise raised

    signer = SpySignatureService(signed_from)
    client = make_client(signer, httpx.MockTransport(handler))

    with pytest.raises(expected):
        await client.request(
            "GET",
            "/client/base/data",
            signature_requirement=SignatureRequirement.PUBLIC,
        )
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(503, text="down"), PupuHttpStatusError),
        (httpx.Response(200, text="<html>"), PupuResponseDecodeError),
        (
            httpx.Response(200, json={"errcode": 4001, "errmsg": "rejected"}),
            PupuBusinessError,
        ),
    ],
)
async def test_response_errors_are_classified(
    response: httpx.Response,
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=response.status_code,
            content=response.content,
            headers=response.headers,
            request=request,
        )

    signer = SpySignatureService(signed_from)
    client = make_client(signer, httpx.MockTransport(handler))

    with pytest.raises(expected):
        await client.request(
            "GET",
            "/client/base/data",
            signature_requirement=SignatureRequirement.PUBLIC,
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_connection_retry_is_bounded_to_idempotent_reads() -> None:
    get_calls = 0

    def get_handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        get_calls += 1
        if get_calls == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"errcode": 0, "data": {}})

    signer = SpySignatureService(signed_from)
    client = make_client(signer, httpx.MockTransport(get_handler), max_read_attempts=2)
    await client.request(
        "GET",
        "/client/base/data",
        signature_requirement=SignatureRequirement.PUBLIC,
    )
    await client.aclose()
    assert get_calls == 2

    post_calls = 0

    def post_handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        post_calls += 1
        raise httpx.ConnectError("connection reset", request=request)

    client = make_client(signer, httpx.MockTransport(post_handler), max_read_attempts=2)
    with pytest.raises(PupuNetworkError):
        await client.request(
            "POST",
            "/client/cart",
            json_body={},
            signature_requirement=SignatureRequirement.PUBLIC,
        )
    await client.aclose()
    assert post_calls == 1


@pytest.mark.asyncio
async def test_read_retries_use_bounded_exponential_backoff() -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"errcode": 0, "data": {}})

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    signer = SpySignatureService(signed_from)
    client = PupuHttpClient(
        base_url="https://j1.pupuapi.com",
        signature_service=signer,
        app_version="6.4.5",
        os_type="Android",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timestamp_ms=lambda: 1_753_036_200_000,
        max_read_attempts=3,
        retry_backoff_seconds=0.25,
        sleep=record_sleep,
    )

    await client.request(
        "GET",
        "/client/base/data",
        signature_requirement=SignatureRequirement.PUBLIC,
    )
    await client.aclose()

    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
async def test_errors_never_include_sensitive_response_or_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=json.dumps(
                {
                    "authorization": "Bearer token-secret",
                    "device_id": "device-secret",
                    "seal": "seal-secret",
                }
            ),
        )

    signer = SpySignatureService(signed_from)
    client = make_client(signer, httpx.MockTransport(handler))

    with pytest.raises(PupuHttpStatusError) as raised:
        await client.request(
            "GET",
            "/client/base/data",
            headers={"Authorization": "Bearer token-secret"},
            signature_requirement=SignatureRequirement.PUBLIC,
        )
    await client.aclose()

    message = str(raised.value).lower()
    assert "token-secret" not in message
    assert "device-secret" not in message
    assert "seal-secret" not in message
