from dataclasses import dataclass
from typing import Protocol

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
