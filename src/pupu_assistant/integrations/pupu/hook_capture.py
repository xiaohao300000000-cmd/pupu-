from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlparse

from pupu_assistant.integrations.pupu.blackbox_signer import (
    SIGNATURE_ARTIFACT_HEADER_NAMES,
    SIGNATURE_HEADER_NAMES,
    BlackboxSignatureUnavailable,
    request_fingerprint,
)

CACHE_HEADER_NAMES = SIGNATURE_HEADER_NAMES | frozenset({"pp-seqid", "pp-time"})

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-auth-token",
        "token",
        "access-token",
        "refresh-token",
    }
)

SENSITIVE_KEY_FRAGMENT_RE = re.compile(
    r"(authorization|cookie|token|secret|password|phone|mobile|sms|code)", re.I
)
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(name).lower(): str(value) for name, value in dict(headers or {}).items()}


def _query_from_url(url: str) -> list[list[str]]:
    parsed = urlparse(url)
    return [
        [str(key), str(value)]
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]


def _path_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or str(url)


def normalize_hook_request(event: Mapping[str, Any]) -> dict[str, Any]:
    request = event.get("request", event)
    if not isinstance(request, Mapping):
        raise BlackboxSignatureUnavailable("hook event request must be an object")

    url = str(request.get("url") or "")
    path = str(request.get("path") or (_path_from_url(url) if url else ""))
    if not path.startswith("/"):
        raise BlackboxSignatureUnavailable("hook event request path missing")

    normalized: dict[str, Any] = {
        "method": str(request.get("method") or "GET").upper(),
        "path": path,
        "query": request.get("query") or (_query_from_url(url) if url else []),
        "headers": _normalize_headers(
            request.get("headers") if isinstance(request, Mapping) else None
        ),
    }
    body_sha256 = request.get("body_sha256")
    if body_sha256 not in (None, ""):
        normalized["body_sha256"] = str(body_sha256)
    context = request.get("context")
    if isinstance(context, Mapping):
        normalized["context"] = dict(context)
    return normalized


def signed_headers_from_hook_event(event: Mapping[str, Any]) -> dict[str, str]:
    request = event.get("request", event)
    if not isinstance(request, Mapping):
        raise BlackboxSignatureUnavailable("hook event request must be an object")
    headers = _normalize_headers(request.get("headers") if isinstance(request, Mapping) else None)
    signed_headers = {
        name: value
        for name, value in headers.items()
        if name in CACHE_HEADER_NAMES or name in SIGNATURE_ARTIFACT_HEADER_NAMES
    }
    if not SIGNATURE_HEADER_NAMES.intersection(signed_headers):
        raise BlackboxSignatureUnavailable("hook event does not contain seal/sign headers")
    return signed_headers


def signature_cache_entry_from_hook_event(event: Mapping[str, Any]) -> dict[str, Any]:
    normalized_request = normalize_hook_request(event)
    fingerprint = request_fingerprint(normalized_request)
    metadata = {
        "source": str(event.get("source") or "frida_hook_capture"),
        "captured_at": str(event.get("timestamp") or datetime.now(UTC).isoformat()),
    }
    if event.get("hook"):
        metadata["hook"] = str(event["hook"])
    return {
        "request_fingerprint": fingerprint,
        "expires_at": None,
        "signed_headers": signed_headers_from_hook_event(event),
        "metadata": metadata,
    }


def upsert_signature_cache_entry(cache: dict[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    cache.setdefault("schema_version", 1)
    entries = cache.setdefault("entries", [])
    if not isinstance(entries, list):
        raise ValueError("cache entries must be a list")
    fingerprint = entry["request_fingerprint"]
    entries[:] = [
        existing
        for existing in entries
        if not isinstance(existing, Mapping)
        or existing.get("request_fingerprint") != fingerprint
    ]
    entries.append(dict(entry))
    return cache


def redact_for_log(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in SENSITIVE_HEADER_NAMES or SENSITIVE_KEY_FRAGMENT_RE.search(key_text):
                redacted[key_text] = f"<REDACTED_SHA256:{_sha256_text(child)[:16]}>"
            elif key_lower in CACHE_HEADER_NAMES:
                redacted[key_text] = f"<SIGNATURE_SHA256:{_sha256_text(child)[:16]}>"
            else:
                redacted[key_text] = redact_for_log(child)
        return redacted
    if isinstance(value, list):
        return [redact_for_log(child) for child in value]
    if isinstance(value, str):
        value = BEARER_RE.sub("Bearer <REDACTED>", value)
        value = PHONE_RE.sub("<PHONE_REDACTED>", value)
        return value
    return value


def redact_hook_event_for_log(event: Mapping[str, Any]) -> dict[str, Any]:
    return redact_for_log(copy.deepcopy(dict(event)))


def cache_to_json(cache: Mapping[str, Any]) -> str:
    return json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
