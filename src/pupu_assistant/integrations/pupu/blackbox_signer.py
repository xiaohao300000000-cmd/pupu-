from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pupu_assistant.integrations.pupu.models import SignatureMode

SIGNATURE_HEADER_NAMES = frozenset(
    {
        "seal",
        "seal-v2",
        "seal-v3",
        "sign",
        "sign-v2",
        "sign-v3",
        "x-pupu-signature-value",
    }
)


class BlackboxSignatureUnavailable(RuntimeError):
    """Raised when no verified black-box signature result was supplied."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _body_bytes(body: Any) -> bytes | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    return _canonical_json_bytes(body)


def _normalize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(name).lower(): str(value) for name, value in dict(headers or {}).items()}


def _normalize_query(query: Any) -> list[list[str]]:
    if query in (None, ""):
        return []
    if isinstance(query, Mapping):
        return [[str(key), str(value)] for key, value in query.items()]
    return [[str(pair[0]), str(pair[1])] for pair in query]


def build_blackbox_signing_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic, log-safe payload shape for a black-box signer.

    The returned object is safe for fixture files: the raw body is replaced by a
    SHA-256 digest marker so credentials, phone numbers, or SMS codes do not get
    persisted by accident. Runtime callers that need the raw body should pass it
    directly to their private signer and only store this normalized shape in Git.
    """

    method = str(request.get("method", request.get("mto", "GET"))).upper()
    path = str(request.get("path", request.get("ah", "")))
    if not path.startswith("/"):
        raise ValueError("Pupu request path must start with '/'")

    body = request.get("body")
    body_digest = request.get("body_sha256")
    body_data = _body_bytes(body)
    if body_digest is None and body_data is not None:
        body_digest = hashlib.sha256(body_data).hexdigest()

    normalized: dict[str, Any] = {
        "method": method,
        "path": path,
        "query": _normalize_query(request.get("query", request.get("query_params"))),
        "headers": _normalize_headers(request.get("headers", request.get("raw_headers"))),
    }
    if body_digest is not None:
        normalized["body_sha256"] = str(body_digest)
        normalized["body"] = "<BODY_SHA256_ONLY>"

    for source_key, target_key in (
        ("app_version", "app_version"),
        ("pp_version", "app_version"),
        ("os_type", "os_type"),
        ("pp_os", "os_type"),
        ("device_id", "pp_device_id"),
        ("pp_device_id", "pp_device_id"),
        ("user_id", "user_id"),
        ("u_user_id", "user_id"),
        ("store_id", "store_id"),
        ("city_zip", "city_zip"),
        ("zip", "city_zip"),
    ):
        value = request.get(source_key)
        if value not in (None, ""):
            normalized[target_key] = str(value)

    return normalized


def _extract_signed_headers(blackbox_result: Mapping[str, Any]) -> dict[str, str]:
    headers = blackbox_result.get("signed_headers", blackbox_result.get("headers"))
    signed_headers = _normalize_headers(headers if isinstance(headers, Mapping) else None)
    if not SIGNATURE_HEADER_NAMES.intersection(signed_headers):
        raise BlackboxSignatureUnavailable(
            "blackbox signature result must contain at least one seal/sign header"
        )
    return signed_headers


def sign_with_supplied_result(
    request: Mapping[str, Any], blackbox_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge a caller-supplied black-box signature result into request headers."""

    normalized = build_blackbox_signing_payload(request)
    signed_headers = _extract_signed_headers(blackbox_result)
    merged_headers = normalized["headers"] | signed_headers
    metadata = dict(blackbox_result.get("metadata") or {})
    metadata.setdefault("source", "supplied_blackbox_result")

    return {
        "ok": True,
        "network_performed": False,
        "signature_mode": SignatureMode.SEAL_SIGN.value,
        "method": normalized["method"],
        "path": normalized["path"],
        "query": normalized["query"],
        "headers": merged_headers,
        "metadata": metadata,
    }


def _run_provider_command(command: str, request: Mapping[str, Any]) -> dict[str, Any]:
    argv = shlex.split(command)
    if not argv:
        raise BlackboxSignatureUnavailable("empty blackbox provider command")
    completed = subprocess.run(
        argv,
        input=json.dumps({"request": request}, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise BlackboxSignatureUnavailable("blackbox provider command failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BlackboxSignatureUnavailable("blackbox provider returned invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise BlackboxSignatureUnavailable("blackbox provider returned non-object JSON")
    return sign_with_supplied_result(request, payload)


def _read_input(path: str | None) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    return data


def _select_case(data: dict[str, Any], case_name: str | None) -> dict[str, Any]:
    cases = data.get("cases")
    if cases is None:
        return data
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    if case_name is None:
        raise ValueError("input contains cases; pass --case <name>")
    for case in cases:
        if isinstance(case, dict) and case.get("name") == case_name:
            return case
    raise ValueError(f"case not found: {case_name}")


def sign_input(data: Mapping[str, Any], provider_command: str | None = None) -> dict[str, Any]:
    request = data.get("request", data)
    if not isinstance(request, Mapping):
        raise ValueError("request must be a JSON object")

    blackbox_result = data.get("blackbox_result")
    if isinstance(blackbox_result, Mapping):
        return sign_with_supplied_result(request, blackbox_result)

    command = provider_command or os.environ.get("PUPUSGN_BLACKBOX_CMD")
    if command:
        return _run_provider_command(command, request)

    raise BlackboxSignatureUnavailable("blackbox signature unavailable")


def _error_payload(message: str, code: str = "blackbox_signature_unavailable") -> dict[str, Any]:
    del message
    return {"ok": False, "network_performed": False, "error": code}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Pupu black-box signature wrapper")
    parser.add_argument("--input", "-i", help="JSON input file; defaults to stdin")
    parser.add_argument("--case", help="case name when input file contains a cases array")
    parser.add_argument(
        "--provider-command",
        help="local command that returns black-box signed_headers JSON; env: PUPUSGN_BLACKBOX_CMD",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)

    try:
        data = _select_case(_read_input(args.input), args.case)
        output = sign_input(data, provider_command=args.provider_command)
        status = 0
    except BlackboxSignatureUnavailable as error:
        output = _error_payload(str(error))
        status = 2
    except Exception:
        output = {"ok": False, "network_performed": False, "error": "invalid_input"}
        status = 2

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
