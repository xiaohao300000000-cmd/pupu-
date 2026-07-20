import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from pupu_assistant.integrations.pupu.models import SignatureMode


class EvidenceContainsSensitiveData(ValueError):
    """Evidence was rejected because it may contain account data or secrets."""


class LiveValidationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: str
    signature_mode: SignatureMode
    tested_at: datetime
    http_status: int | None
    pupu_errcode: int | str | None
    request_result: Literal["passed", "failed"]
    response_shape: dict[str, Any]
    verified_in_mobile_app: bool
    failure_reason: str | None


_SENSITIVE_KEYS = {
    "access_token",
    "address",
    "authorization",
    "cookie",
    "device_id",
    "latitude",
    "longitude",
    "phone",
    "pp_suid",
    "pp_userid",
    "refresh_token",
    "seal",
    "sign",
    "su_id",
    "user_id",
}
_SENSITIVE_VALUES = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(
        r"(?i)\b(?:access_token|authorization|cookie|refresh_token|seal|sign)\s*[:=]"
    ),
)


def evidence_shape(value: Any) -> Any:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "keys": {
                str(key): evidence_shape(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            },
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {
            "type": "array",
            "items": evidence_shape(value[0]) if value else "unknown",
        }
    return type(value).__name__


def _assert_safe(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if normalized_key in _SENSITIVE_KEYS:
                raise EvidenceContainsSensitiveData(
                    "Validation evidence contains a forbidden field"
                )
            _assert_safe(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_safe(item)
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SENSITIVE_VALUES):
        raise EvidenceContainsSensitiveData(
            "Validation evidence contains a forbidden value"
        )


def write_evidence(
    target: Path,
    evidence: LiveValidationEvidence | Mapping[str, Any],
) -> None:
    payload = (
        evidence.model_dump(mode="json")
        if isinstance(evidence, LiveValidationEvidence)
        else dict(evidence)
    )
    _assert_safe(payload)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.write("\n")
            temporary_path = temporary.name
        os.replace(temporary_path, target)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
