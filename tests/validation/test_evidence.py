import json
from datetime import UTC, datetime

import pytest

from pupu_assistant.integrations.pupu.models import SignatureMode
from pupu_assistant.validation.evidence import (
    EvidenceContainsSensitiveData,
    LiveValidationEvidence,
    evidence_shape,
    write_evidence,
)


def safe_evidence() -> LiveValidationEvidence:
    return LiveValidationEvidence(
        endpoint="/client/base/data",
        signature_mode=SignatureMode.NONE,
        tested_at=datetime(2026, 7, 20, 19, 30, tzinfo=UTC),
        http_status=200,
        pupu_errcode=0,
        request_result="passed",
        response_shape={
            "type": "object",
            "keys": {"errcode": "integer", "data": "object"},
        },
        verified_in_mobile_app=False,
        failure_reason=None,
    )


def test_evidence_writer_persists_safe_structural_data(tmp_path) -> None:
    target = tmp_path / "evidence.json"

    write_evidence(target, safe_evidence())

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["endpoint"] == "/client/base/data"
    assert stored["signature_mode"] == "none"
    assert stored["request_result"] == "passed"
    assert stored["verified_in_mobile_app"] is False


@pytest.mark.parametrize(
    "unsafe",
    [
        {"authorization": "Bearer token-secret"},
        {"metadata": {"refresh_token": "refresh-secret"}},
        {"failure_reason": "request used Bearer token-secret"},
        {"failure_reason": "phone 13800138000"},
        {"failure_reason": "seal=seal-secret"},
    ],
)
def test_evidence_writer_rejects_sensitive_keys_and_values(tmp_path, unsafe) -> None:
    target = tmp_path / "unsafe.json"
    evidence = safe_evidence().model_dump(mode="json")
    evidence.update(unsafe)

    with pytest.raises(EvidenceContainsSensitiveData):
        write_evidence(target, evidence)

    assert not target.exists()


def test_evidence_shape_records_types_and_keys_not_values() -> None:
    payload = {
        "errcode": 0,
        "data": {
            "server_time": 1_753_036_200_123,
            "items": [{"name": "sensitive-product-name", "price": 123}],
        },
    }

    shape = evidence_shape(payload)
    serialized = json.dumps(shape, ensure_ascii=False)

    assert shape["type"] == "object"
    assert shape["keys"]["data"]["keys"]["server_time"] == "integer"
    assert "sensitive-product-name" not in serialized
    assert "1753036200123" not in serialized
