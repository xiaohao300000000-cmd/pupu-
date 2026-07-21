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


def product_sdu_request() -> dict[str, object]:
    return {
        "method": "GET",
        "path": "/client/product/storeproduct/detail_popup/<STORE_ID>/<STORE_PRODUCT_ID>",
        "query": [["zip", "<CITY_ZIP>"], ["source", "product_detail"]],
        "headers": {
            "pp-version": "6.4.9",
            "pp-os": "20",
            "pp-deviceid": "<PP_DEVICE_ID>",
            "pp-time": "<TIMESTAMP_MS>",
        },
        "context": {
            "app_version": "6.4.9",
            "os_type": "20",
            "pp_device_id": "<PP_DEVICE_ID>",
            "user_id": "<USER_ID>",
            "store_id": "<STORE_ID>",
            "city_zip": "<CITY_ZIP>",
        },
    }


def cart_sdu_request() -> dict[str, object]:
    return {
        "method": "POST",
        "path": "/client/shopping_cart/shopping_cart_item/bff/purchasing_product",
        "query": [["store_id", "<STORE_ID>"], ["purchase_pattern", "normal"]],
        "body": {
            "items": [
                {
                    "store_product_id": "<STORE_PRODUCT_ID>",
                    "product_id": "<PRODUCT_ID>",
                    "quantity": 1,
                }
            ],
            "page_source": "product_detail",
        },
        "headers": {
            "pp-version": "6.4.9",
            "pp-os": "20",
            "pp-deviceid": "<PP_DEVICE_ID>",
            "pp-time": "<TIMESTAMP_MS>",
        },
        "context": {
            "app_version": "6.4.9",
            "os_type": "20",
            "pp_device_id": "<PP_DEVICE_ID>",
            "user_id": "<USER_ID>",
            "store_id": "<STORE_ID>",
            "city_zip": "<CITY_ZIP>",
        },
    }


def write_fake_sdu_signer(tmp_path: Path) -> tuple[Path, Path]:
    signer = tmp_path / "fake_sdu_signer.py"
    record = tmp_path / "seen-by-sdu.json"
    signer.write_text(
        """
import json
import sys
from pathlib import Path

record = Path(sys.argv[1])
payload = json.load(sys.stdin)
record.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
request = payload["request"]
print(json.dumps({
    "signed_headers": {
        "seal": "<SDU_SEAL>",
        "sign-v3": "<SDU_SIGN_V3>",
        "pp-seqid": "<SDU_SEQID>",
        "pp-time": request["headers"].get("pp-time", "<TIMESTAMP_MS>"),
    },
    "metadata": {"source": "fake_sdu", "path": request["path"]},
}))
""".lstrip(),
        encoding="utf-8",
    )
    return signer, record


@pytest.mark.parametrize("request_payload", [product_sdu_request(), cart_sdu_request()])
def test_pupusgn_stdin_calls_local_sdu_with_complete_request(
    tmp_path: Path, request_payload: dict[str, object]
) -> None:
    signer, record = write_fake_sdu_signer(tmp_path)
    command = f"{sys.executable} {signer} {record}"

    completed = subprocess.run(
        [sys.executable, ".local/bin/pupusgn", "--sdu-command", command],
        input=json.dumps({"request": request_payload}),
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(completed.stdout)
    seen_by_sdu = json.loads(record.read_text(encoding="utf-8"))
    invoked = seen_by_sdu["request"]

    assert output["ok"] is True
    assert output["network_performed"] is False
    assert output["headers"]["seal"] == "<SDU_SEAL>"
    assert output["headers"]["sign-v3"] == "<SDU_SIGN_V3>"
    assert output["headers"]["pp-seqid"] == "<SDU_SEQID>"
    assert seen_by_sdu["schema_version"] == 1
    assert invoked["method"] == request_payload["method"]
    assert invoked["path"] == request_payload["path"]
    assert invoked["query"] == request_payload["query"]
    assert invoked["headers"]["pp-deviceid"] == "<PP_DEVICE_ID>"
    assert invoked["context"]["pp_device_id"] == "<PP_DEVICE_ID>"
    if request_payload["method"] == "POST":
        assert invoked["body"] == request_payload["body"]
        assert len(invoked["body_sha256"]) == 64


def test_committed_sdu_fixture_runs_product_and_cart_cases(tmp_path: Path) -> None:
    fixture = Path(".local/pupusgn-sdu-input.json")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    cases = {case["name"] for case in data["cases"]}
    assert cases >= {"sdu_product_detail_popup", "sdu_cart_purchasing_product"}

    signer, record = write_fake_sdu_signer(tmp_path)
    command = f"{sys.executable} {signer} {record}"
    for case_name in sorted(cases):
        completed = subprocess.run(
            [
                sys.executable,
                ".local/bin/pupusgn",
                "--input",
                str(fixture),
                "--case",
                case_name,
                "--sdu-command",
                command,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(completed.stdout)
        assert output["ok"] is True
        assert output["network_performed"] is False
        assert output["headers"]["seal"] == "<SDU_SEAL>"


def test_pupusgn_accepts_short_field_stdin_for_local_sdu(tmp_path: Path) -> None:
    signer, record = write_fake_sdu_signer(tmp_path)
    command = f"{sys.executable} {signer} {record}"
    short_request = {
        "mto": "POST",
        "at": "/client/shopping_cart/shopping_cart_item/bff/purchasing_product",
        "query": [["store_id", "<STORE_ID>"]],
        "uybd": {"items": [{"store_product_id": "<STORE_PRODUCT_ID>", "quantity": 1}]},
        "edr": {
            "pp-version": "6.4.9",
            "pp-os": "20",
            "pp-deviceid": "<PP_DEVICE_ID>",
            "pp-time": "<TIMESTAMP_MS>",
        },
        "context": {
            "pp_device_id": "<PP_DEVICE_ID>",
            "user_id": "<USER_ID>",
            "store_id": "<STORE_ID>",
            "city_zip": "<CITY_ZIP>",
        },
    }

    completed = subprocess.run(
        [sys.executable, ".local/bin/pupusgn", "--sdu-command", command],
        input=json.dumps({"request": short_request}),
        check=True,
        capture_output=True,
        text=True,
    )

    output = json.loads(completed.stdout)
    seen_by_sdu = json.loads(record.read_text(encoding="utf-8"))
    invoked = seen_by_sdu["request"]

    assert output["ok"] is True
    assert output["headers"]["seal"] == "<SDU_SEAL>"
    assert invoked["method"] == "POST"
    assert invoked["path"] == short_request["at"]
    assert invoked["body"] == short_request["uybd"]
    assert invoked["headers"]["pp-deviceid"] == "<PP_DEVICE_ID>"
    assert invoked["context"]["user_id"] == "<USER_ID>"
    assert len(invoked["body_sha256"]) == 64
