import json
from dataclasses import dataclass
from typing import Protocol

from pupu_assistant.integrations.pupu.blackbox_signer import (
    BlackboxSignatureUnavailable,
    sign_input,
)
from pupu_assistant.integrations.pupu.models import (
    PupuRequestContext,
    SignatureMode,
    SignedPupuRequest,
)


class ProtectedSignatureUnavailable(RuntimeError):
    """Raised before transport when a protected request cannot be signed."""


class PupuSignatureService(Protocol):
    def sign(self, request: PupuRequestContext) -> SignedPupuRequest: ...


def _normalize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {name.lower(): value for name, value in headers.items()}


@dataclass(frozen=True, slots=True)
class ExplicitNoSignatureService:
    public_paths: frozenset[str]

    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        if request.path not in self.public_paths:
            raise ProtectedSignatureUnavailable(
                "A verified signature implementation is required for this Pupu route"
            )
        return SignedPupuRequest(
            path=request.path,
            query=tuple(request.query),
            body=request.body,
            headers=_normalize_headers(request.existing_headers),
            signature_mode=SignatureMode.NONE,
            metadata={"reason": "explicit_public_route"},
        )


@dataclass(frozen=True, slots=True)
class UnavailableProtectedSignatureService:
    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        del request
        raise ProtectedSignatureUnavailable(
            "A verified seal/sign implementation is not available"
        )


@dataclass(frozen=True, slots=True)
class ExternalBlackboxSignatureService:
    """Adapts an account-owner supplied signer command to the protected contract."""

    provider_command: str

    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        if not self.provider_command.strip():
            raise ProtectedSignatureUnavailable(
                "The external black-box signer command is not configured"
            )
        try:
            result = sign_input(
                {"request": self._provider_request(request)},
                provider_command=self.provider_command,
            )
        except BlackboxSignatureUnavailable as error:
            raise ProtectedSignatureUnavailable(
                "The external black-box signer did not return verified headers"
            ) from error

        headers = result.get("headers")
        if result.get("ok") is not True or not isinstance(headers, dict):
            raise ProtectedSignatureUnavailable(
                "The external black-box signer returned an invalid result"
            )
        metadata = {
            str(key): str(value)
            for key, value in dict(result.get("metadata") or {}).items()
        }
        metadata["provider"] = "external_blackbox_command"
        return SignedPupuRequest(
            path=request.path,
            query=request.query,
            body=request.body,
            headers={str(name).lower(): str(value) for name, value in headers.items()},
            signature_mode=SignatureMode.SEAL_SIGN,
            metadata=metadata,
        )

    @staticmethod
    def _provider_request(request: PupuRequestContext) -> dict[str, object]:
        headers = _normalize_headers(request.existing_headers)
        headers.update(
            {
                "pp-version": request.app_version,
                "pp-os": request.os_type,
                "pp-time": str(request.timestamp_ms),
            }
        )
        optional_headers = {
            "pp-deviceid": request.device_id,
            "pp-userid": request.user_id,
            "pp-suid": request.su_id,
            "pp-storeid": request.store_id,
            "pp-placeid": request.place_id,
        }
        headers.update(
            {
                name: value
                for name, value in optional_headers.items()
                if value is not None
            }
        )
        payload: dict[str, object] = {
            "method": request.method,
            "path": request.path,
            "query": [list(pair) for pair in request.query],
            "headers": headers,
            "timestamp_ms": request.timestamp_ms,
            "app_version": request.app_version,
            "os_type": request.os_type,
        }
        optional_context = {
            "pp_device_id": request.device_id,
            "user_id": request.user_id,
            "suid": request.su_id,
            "store_id": request.store_id,
            "place_id": request.place_id,
            "city_zip": request.city_zip,
        }
        payload.update(
            {
                name: value
                for name, value in optional_context.items()
                if value is not None
            }
        )
        if request.body is not None:
            body_text = request.body.decode("utf-8")
            try:
                payload["body"] = json.loads(body_text)
            except json.JSONDecodeError:
                payload["body"] = body_text
        return payload


@dataclass(frozen=True, slots=True)
class RoutingPupuSignatureService:
    public_service: PupuSignatureService
    protected_service: PupuSignatureService
    public_paths: frozenset[str]

    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        service = (
            self.public_service
            if request.path in self.public_paths
            else self.protected_service
        )
        return service.sign(request)
