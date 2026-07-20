from copy import deepcopy

import pytest
from pydantic import ValidationError

from pupu_assistant.integrations.pupu.models import (
    PupuRequestContext,
    SignatureMode,
)
from pupu_assistant.integrations.pupu.signature import (
    ExplicitNoSignatureService,
    ProtectedSignatureUnavailable,
    RoutingPupuSignatureService,
    UnavailableProtectedSignatureService,
)


def request_context(
    *,
    path: str = "/client/base/data",
    headers: dict[str, str] | None = None,
) -> PupuRequestContext:
    return PupuRequestContext(
        method="get",
        path=path,
        query=(("city_zip", "350100"),),
        body=None,
        timestamp_ms=1_753_036_200_000,
        device_id="device-secret",
        user_id="user-secret",
        su_id="suid-secret",
        store_id="store-1",
        place_id="place-1",
        city_zip="350100",
        app_version="6.4.5",
        os_type="Android",
        existing_headers=headers or {"X-Trace": "one"},
    )


def test_request_context_normalizes_method_and_is_frozen() -> None:
    context = request_context()

    assert context.method == "GET"
    with pytest.raises(ValidationError):
        context.method = "POST"


def test_explicit_none_mode_normalizes_headers_without_mutating_input() -> None:
    original_headers = {"X-Trace": "one", "x-trace": "two", "Accept": "application/json"}
    context = request_context(headers=deepcopy(original_headers))
    service = ExplicitNoSignatureService(
        public_paths=frozenset({"/client/base/data"}),
    )

    signed = service.sign(context)

    assert signed.signature_mode is SignatureMode.NONE
    assert signed.headers == {"accept": "application/json", "x-trace": "two"}
    assert context.existing_headers == original_headers
    assert signed.metadata == {"reason": "explicit_public_route"}

    signed.headers["x-trace"] = "changed"
    assert context.existing_headers["x-trace"] == "two"


def test_explicit_none_mode_rejects_unlisted_route() -> None:
    service = ExplicitNoSignatureService(
        public_paths=frozenset({"/client/base/data"}),
    )

    with pytest.raises(ProtectedSignatureUnavailable):
        service.sign(request_context(path="/client/cart"))


def test_unavailable_protected_signer_fails_closed_without_leaking_context() -> None:
    context = request_context(
        path="/client/cart",
        headers={
            "Authorization": "Bearer token-secret",
            "seal": "seal-secret",
            "sign": "sign-secret",
        },
    )

    with pytest.raises(ProtectedSignatureUnavailable) as raised:
        UnavailableProtectedSignatureService().sign(context)

    message = str(raised.value).lower()
    for secret in (
        "token-secret",
        "device-secret",
        "user-secret",
        "suid-secret",
        "seal-secret",
        "sign-secret",
    ):
        assert secret not in message


def test_router_selects_public_and_protected_services() -> None:
    public = ExplicitNoSignatureService(
        public_paths=frozenset({"/client/base/data"}),
    )
    router = RoutingPupuSignatureService(
        public_service=public,
        protected_service=UnavailableProtectedSignatureService(),
        public_paths=frozenset({"/client/base/data"}),
    )

    assert router.sign(request_context()).signature_mode is SignatureMode.NONE
    with pytest.raises(ProtectedSignatureUnavailable):
        router.sign(request_context(path="/client/cart"))
