from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
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
SIGNATURE_ARTIFACT_HEADER_NAMES = SIGNATURE_HEADER_NAMES | frozenset(
    {
        "pp-seqid",
        "pp-time",
        "x-pupu-signature-timestamp",
        "x-pupu-signature-version",
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


def _first_present(request: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = request.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested_context(request: Mapping[str, Any]) -> Mapping[str, Any]:
    context = request.get("context", request.get("device_context"))
    return context if isinstance(context, Mapping) else {}


def _context_value(request: Mapping[str, Any], *keys: str) -> Any:
    context = _nested_context(request)
    value = _first_present(context, *keys)
    if value not in (None, ""):
        return value
    return _first_present(request, *keys)


def _request_method(request: Mapping[str, Any]) -> str:
    return str(_first_present(request, "method", "mto") or "GET").upper()


def _request_path(request: Mapping[str, Any]) -> str:
    return str(_first_present(request, "path", "ah", "at", "url_path", "uri") or "")


def _request_headers(request: Mapping[str, Any]) -> dict[str, str]:
    headers = _first_present(request, "headers", "raw_headers", "hadr", "edr")
    return _normalize_headers(headers if isinstance(headers, Mapping) else None)


def _request_body(request: Mapping[str, Any]) -> Any:
    return _first_present(request, "body", "request_body", "uybd")


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

    method = _request_method(request)
    path = _request_path(request)
    if not path.startswith("/"):
        raise ValueError("Pupu request path must start with '/'")

    body = _request_body(request)
    body_digest = request.get("body_sha256")
    body_data = _body_bytes(body)
    if body_digest is None and body_data is not None:
        body_digest = hashlib.sha256(body_data).hexdigest()

    normalized: dict[str, Any] = {
        "method": method,
        "path": path,
        "query": _normalize_query(request.get("query", request.get("query_params"))),
        "headers": _request_headers(request),
    }
    if body_digest is not None:
        normalized["body_sha256"] = str(body_digest)
        normalized["body"] = "<BODY_SHA256_ONLY>"

    context = _collect_context(request)
    normalized.update(context)

    return normalized


def _collect_context(request: Mapping[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    for source_keys, target_key in (
        (("app_version", "pp_version"), "app_version"),
        (("os_type", "pp_os"), "os_type"),
        (("device_id", "pp_device_id"), "pp_device_id"),
        (("user_id", "u_user_id"), "user_id"),
        (("su_id", "suid", "pp_suid"), "su_id"),
        (("store_id", "pp_store_id"), "store_id"),
        (("place_id", "pp_place_id"), "place_id"),
        (("city_zip", "zip", "place_zip"), "city_zip"),
    ):
        value = _context_value(request, *source_keys)
        if value not in (None, ""):
            context[target_key] = str(value)
    return context


def build_signer_invocation_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build the full stdin payload sent to the private local signer command."""

    signer_request = dict(build_blackbox_signing_payload(request))
    body = _request_body(request)
    if body is not None:
        signer_request["body"] = body
        body_data = _body_bytes(body)
        if body_data is not None:
            signer_request["body_sha256"] = hashlib.sha256(body_data).hexdigest()
    signer_request["context"] = _collect_context(request)
    return {"schema_version": 1, "request": signer_request}


def request_fingerprint(request: Mapping[str, Any]) -> str:
    """Return a secret-free exact-match fingerprint for a signed request.

    The fingerprint includes method, path, query, normalized non-signature
    headers, context, and the body SHA-256. It never stores raw request bodies.
    """

    normalized = build_blackbox_signing_payload(request)
    headers = normalized.get("headers")
    if isinstance(headers, Mapping):
        normalized["headers"] = {
            str(name).lower(): str(value)
            for name, value in headers.items()
            if str(name).lower() not in SIGNATURE_ARTIFACT_HEADER_NAMES
        }
    digest = hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()
    return f"sha256:{digest}"


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
    argv = shlex.split(command, posix=os.name != "nt")
    if not argv:
        raise BlackboxSignatureUnavailable("empty blackbox provider command")
    completed = subprocess.run(
        argv,
        input=json.dumps(build_signer_invocation_payload(request), ensure_ascii=False),
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


def _parse_expiry(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise BlackboxSignatureUnavailable("signature cache entry has invalid expiry")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BlackboxSignatureUnavailable("signature cache entry has invalid expiry") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def sign_with_signature_cache(
    request: Mapping[str, Any],
    cache_path: str | os.PathLike[str],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge real, pre-captured signed headers from an exact-match cache."""

    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    if not isinstance(cache, Mapping):
        raise BlackboxSignatureUnavailable("signature cache must be a JSON object")
    entries = cache.get("entries")
    if not isinstance(entries, list):
        raise BlackboxSignatureUnavailable("signature cache entries must be a list")

    fingerprint = request_fingerprint(request)
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("request_fingerprint") != fingerprint:
            continue
        expires_at = _parse_expiry(entry.get("expires_at"))
        if expires_at is not None and expires_at <= current_time:
            raise BlackboxSignatureUnavailable("signature cache entry expired")
        signed_headers = entry.get("signed_headers", entry.get("headers"))
        metadata = dict(entry.get("metadata") or {})
        metadata.setdefault("source", "signature_cache")
        metadata["request_fingerprint"] = fingerprint
        return sign_with_supplied_result(
            request,
            {"signed_headers": signed_headers, "metadata": metadata},
        )

    raise BlackboxSignatureUnavailable("signature cache miss")


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


def sign_input(
    data: Mapping[str, Any],
    provider_command: str | None = None,
    sdu_command: str | None = None,
    signature_cache: str | None = None,
) -> dict[str, Any]:
    request = data.get("request", data)
    if not isinstance(request, Mapping):
        raise ValueError("request must be a JSON object")

    blackbox_result = data.get("blackbox_result")
    if isinstance(blackbox_result, Mapping):
        return sign_with_supplied_result(request, blackbox_result)

    command = (
        sdu_command
        or provider_command
        or data.get("sdu_command")
        or data.get("signer_command")
        or os.environ.get("PUPUSGN_SDU_CMD")
        or os.environ.get("PUPUSGN_BLACKBOX_CMD")
    )
    if isinstance(command, str) and command:
        return _run_provider_command(command, request)

    cache_path = (
        signature_cache
        or data.get("signature_cache")
        or data.get("signature_cache_path")
        or os.environ.get("PUPUSGN_SIGNATURE_CACHE")
    )
    if isinstance(cache_path, str) and cache_path:
        return sign_with_signature_cache(request, cache_path)

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
    parser.add_argument(
        "--sdu-command",
        help="local private signer/SDK command; env: PUPUSGN_SDU_CMD",
    )
    parser.add_argument(
        "--signature-cache",
        help=(
            "exact-match cache with real pre-captured signed headers; "
            "env: PUPUSGN_SIGNATURE_CACHE"
        ),
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    args = parser.parse_args(argv)

    try:
        data = _select_case(_read_input(args.input), args.case)
        output = sign_input(
            data,
            provider_command=args.provider_command,
            sdu_command=args.sdu_command,
            signature_cache=args.signature_cache,
        )
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
