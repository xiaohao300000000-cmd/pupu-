from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class SignatureMode(StrEnum):
    NONE = "none"
    SEAL_SIGN = "seal_sign"


class SignatureRequirement(StrEnum):
    PUBLIC = "public"
    PROTECTED = "protected"


class PupuRequestContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    query: tuple[tuple[str, str], ...] = ()
    body: bytes | None = None
    timestamp_ms: int
    device_id: str | None = None
    user_id: str | None = None
    su_id: str | None = None
    store_id: str | None = None
    place_id: str | None = None
    city_zip: str | None = None
    app_version: str
    os_type: str
    existing_headers: dict[str, str] = {}

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper()

    @field_validator("path")
    @classmethod
    def require_absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Pupu request path must start with '/'")
        return value


class SignedPupuRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    query: tuple[tuple[str, str], ...] = ()
    body: bytes | None = None
    headers: dict[str, str]
    signature_mode: SignatureMode
    metadata: dict[str, str]


class PupuResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status_code: int
    errcode: int | str | None
    data: Any
    payload: Any
