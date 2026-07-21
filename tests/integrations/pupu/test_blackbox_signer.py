import json
import subprocess
import sys
from pathlib import Path

import pytest

from pupu_assistant.integrations.pupu.blackbox_signer import (
    BlackboxSignatureUnavailable,
    build_blackbox_signing_payload,
    sign_with_supplied_result,
)


def minimal_payload() -> dict[str, object]:
    return {
        "method": "GET",
        "path": "/client/product/storeproduct/detail_popup/demo-store/demo-product",
        "query": [["zip", "<CITY_ZIP>"]],
        "headers": {
            "pp-version": "6.4.9",
            "pp-os": "20",
            "pp-deviceid": "<PP_DEVICE_ID>",
            "pp-time": "<TIMESTAMP_MS>",
        },
    }


def supplied_result() -> dict[str, object]:
    return {
        "signed_headers": {
            "seal": "<BLACKBOX_SEAL>",
            "sign-v3": "<BLACKBOX_SIGN_V3>",
            "pp-seqid": "<BLACKBOX_SEQID>",
            "pp-time": "<TIMESTAMP_MS>",
        },
        "metadata": {"source": "hook_capture_redacted"},
    }


def test_sign_with_supplied_result_merges_headers_and_marks_blackbox() -> None:
    signed = sign_with_supplied_result(minimal_payload(), supplied_result())

    assert signed["ok"] is True
    assert signed["network_performed"] is False
    assert signed["signature_mode"] == "seal_sign"
    assert signed["headers"]["pp-version"] == "6.4.9"
    assert signed["headers"]["seal"] == "<BLACKBOX_SEAL>"
    assert signed["headers"]["sign-v3"] == "<BLACKBOX_SIGN_V3>"
    assert signed["metadata"]["source"] == "hook_capture_redacted"


def test_sign_with_supplied_result_requires_a_signature_header() -> None:
    with pytest.raises(BlackboxSignatureUnavailable):
        sign_with_supplied_result(minimal_payload(), {"signed_headers": {"pp-time": "1"}})


def test_build_blackbox_signing_payload_redacts_body_and_preserves_shape() -> None:
    payload = minimal_payload() | {
        "method": "POST",
        "body": {
            "store_id": "<STORE_ID>",
            "items": [{"product_id": "<STORE_PRODUCT_ID>", "quantity": 1}],
        },
    }

    normalized = build_blackbox_signing_payload(payload)

    assert normalized["method"] == "POST"
    assert normalized["path"].startswith("/")
    assert normalized["body_sha256"]
    assert normalized["body"] == "<BODY_SHA256_ONLY>"
    assert normalized["headers"]["pp-deviceid"] == "<PP_DEVICE_ID>"


def test_pupusgn_cli_accepts_supplied_result_from_file(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "request": minimal_payload(),
                "blackbox_result": supplied_result(),
            }
        ),
        encoding="utf-8",
    )

    script = Path(".local/bin/pupusgn")
    completed = subprocess.run(
        [sys.executable, str(script), "--input", str(fixture)],
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(completed.stdout)
    assert output["ok"] is True
    assert output["network_performed"] is False
    assert output["headers"]["seal"] == "<BLACKBOX_SEAL>"


def test_pupusgn_cli_fails_closed_without_blackbox_result() -> None:
    script = Path(".local/bin/pupusgn")
    completed = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"request": minimal_payload()}),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    output = json.loads(completed.stdout)
    assert output["ok"] is False
    assert output["error"] == "blackbox_signature_unavailable"
    assert output["network_performed"] is False


def test_committed_pupusgn_fixture_contains_two_runnable_cases() -> None:
    fixture = Path(".local/pupusgn-test.json")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    cases = {case["name"] for case in data["cases"]}

    assert cases >= {
        "protected_read_product_detail_popup",
        "business_write_cart_purchasing_product",
    }
    for case_name in sorted(cases):
        completed = subprocess.run(
            [sys.executable, ".local/bin/pupusgn", "--input", str(fixture), "--case", case_name],
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(completed.stdout)
        assert output["ok"] is True
        assert output["network_performed"] is False


def test_committed_pupu_cases_are_redacted() -> None:
    cases = Path(".local/pupu-cases.json")
    text = cases.read_text(encoding="utf-8")

    forbidden_fragments = [
        "Bear" + "er ",
        "Author" + "ization",
        "pass" + "word",
        "s" + "ms",
        "\u9a8c" + "\u8bc1\u7801",
        "\u624b\u673a" + "\u53f7",
    ]
    assert not any(fragment in text for fragment in forbidden_fragments)
    assert "138" + "00138000" not in text
    assert "<PP_DEVICE_ID>" in text
    assert "<STORE_ID>" in text
