#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pupu_assistant.config import Settings
from pupu_assistant.integrations.pupu.blackbox_signer import BlackboxPupuSignatureService
from pupu_assistant.integrations.pupu.client import PupuHttpClient
from pupu_assistant.integrations.pupu.models import SignatureRequirement
from pupu_assistant.validation.evidence import evidence_shape, write_evidence

DEFAULT_INPUT = Path(".local/private/pupu-live-request.json")
DEFAULT_EVIDENCE = Path(".local/evidence/protected-live-validation.json")
SAFE_READ_METHODS = frozenset({"GET", "HEAD"})


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("validation input must be a JSON object")
    return data


def _request_object(config: Mapping[str, Any]) -> Mapping[str, Any]:
    request = config.get("request", config)
    if not isinstance(request, Mapping):
        raise ValueError("request must be a JSON object")
    return request


def _query(request: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    query = request.get("query", request.get("query_params", ()))
    if isinstance(query, Mapping):
        return tuple((str(key), str(value)) for key, value in query.items())
    return tuple((str(item[0]), str(item[1])) for item in query or ())


def _headers(request: Mapping[str, Any]) -> dict[str, str]:
    headers = request.get("headers", request.get("edr", {}))
    if not isinstance(headers, Mapping):
        return {}
    return {str(key): str(value) for key, value in headers.items()}


def _context(config: Mapping[str, Any], request: Mapping[str, Any]) -> Mapping[str, Any]:
    context = request.get("context", config.get("context", {}))
    return context if isinstance(context, Mapping) else {}


def _body(request: Mapping[str, Any]) -> Any:
    return request.get("body", request.get("request_body", request.get("uybd")))


def _context_value(context: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = context.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _redacted_evidence(
    *,
    input_path: Path,
    mode: str,
    method: str,
    path: str,
    status_code: int | None,
    payload: Any | None,
    failure: str | None,
) -> dict[str, Any]:
    errcode = payload.get("errcode") if isinstance(payload, dict) else None
    return {
        "schema_version": 1,
        "tested_at": datetime.now(UTC).isoformat(),
        "input_path": str(input_path),
        "seal_v3_mode": mode,
        "method": method,
        "path": path,
        "http_status": status_code,
        "pupu_errcode": errcode,
        "request_result": "passed" if failure is None else "failed",
        "failure_reason": failure,
        "response_shape": evidence_shape(payload) if payload is not None else {},
    }


async def _attempt(
    *,
    settings: Settings,
    config: Mapping[str, Any],
    request: Mapping[str, Any],
    input_path: Path,
    evidence_path: Path,
    mode: str,
    signer_command: str | None,
) -> dict[str, Any]:
    method = str(request.get("method", request.get("mto", "GET"))).upper()
    path = str(request.get("path", request.get("ah", request.get("at", ""))))
    context = _context(config, request)

    if method not in SAFE_READ_METHODS and not settings.pupu_allow_live_mutation:
        raise ValueError("live mutation is disabled; set PUPU_ALLOW_LIVE_MUTATION=true")

    raw_client = httpx.AsyncClient(
        timeout=settings.pupu_timeout_seconds,
        verify=settings.pupu_verify_tls,
        headers={"user-agent": f"pupu-android/{settings.pupu_app_version}"},
    )
    client = PupuHttpClient(
        base_url=str(config.get("base_url") or settings.pupu_base_url),
        signature_service=BlackboxPupuSignatureService(
            mixmaster_command=signer_command or config.get("mixmaster_command"),
            sdu_command=config.get("sdu_command"),
            provider_command=config.get("signer_command"),
            signature_cache=config.get("signature_cache"),
            seal_v3_mode=mode,
        ),
        app_version=str(config.get("app_version") or settings.pupu_app_version),
        os_type=str(config.get("os_type") or settings.pupu_os_type),
        http_client=raw_client,
        timestamp_ms=lambda: int(time.time() * 1000),
        max_read_attempts=1,
        device_id=_context_value(context, "pp_device_id", "device_id"),
        user_id=_context_value(context, "user_id", "pp_userid"),
        su_id=_context_value(context, "su_id", "suid", "pp_suid"),
        store_id=_context_value(context, "store_id", "pp_storeid", "pp_store_id"),
        place_id=_context_value(context, "place_id", "pp_placeid", "pp_place_id"),
        city_zip=_context_value(context, "city_zip", "zip", "place_zip"),
    )
    try:
        response = await client.request(
            method,
            path,
            query=_query(request),
            json_body=_body(request),
            headers=_headers(request),
            signature_requirement=SignatureRequirement.PROTECTED,
        )
        evidence = _redacted_evidence(
            input_path=input_path,
            mode=mode,
            method=method,
            path=path,
            status_code=response.status_code,
            payload=response.payload,
            failure=None,
        )
    except Exception as error:
        evidence = _redacted_evidence(
            input_path=input_path,
            mode=mode,
            method=method,
            path=path,
            status_code=None,
            payload=None,
            failure=type(error).__name__,
        )
    finally:
        await client.aclose()

    write_evidence(evidence_path, evidence)
    return evidence


async def validate(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(
            "missing private validation input: "
            f"{input_path}; copy .local/pupu-live-request.example.json"
        )
    config = _read_json(input_path)
    request = _request_object(config)
    modes = ("full", "s2") if args.seal_mode == "auto" else (args.seal_mode,)

    last_evidence: dict[str, Any] | None = None
    for mode in modes:
        evidence = await _attempt(
            settings=Settings(),
            config=config,
            request=request,
            input_path=input_path,
            evidence_path=Path(args.evidence),
            mode=mode,
            signer_command=args.mixmaster_command,
        )
        last_evidence = evidence
        if evidence["request_result"] == "passed":
            print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
            return 0

    print(json.dumps(last_evidence or {}, ensure_ascii=False, sort_keys=True))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one protected Pupu API request")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="private request JSON")
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE), help="redacted evidence JSON")
    parser.add_argument("--seal-mode", choices=("auto", "full", "s2"), default="auto")
    parser.add_argument("--mixmaster-command", help="override pupusgn-compatible mixmaster command")
    try:
        return asyncio.run(validate(parser.parse_args()))
    except FileNotFoundError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "request_result": "not_run",
                    "failure_reason": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
