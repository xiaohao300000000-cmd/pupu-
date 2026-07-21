import json
from pathlib import Path

from pupu_assistant.integrations.pupu.hook_capture import (
    cache_to_json,
    normalize_hook_request,
    redact_hook_event_for_log,
    signature_cache_entry_from_hook_event,
    upsert_signature_cache_entry,
)


def sample_hook_event() -> dict[str, object]:
    return {
        "kind": "http_request",
        "source": "frida_hook_capture",
        "hook": "okhttp3.internal.http.RealInterceptorChain.proceed",
        "timestamp": "2026-07-22T01:02:03Z",
        "request": {
            "method": "GET",
            "url": "https://j1.pupuapi.com/client/product/storeproduct/detail_popup/s/p?zip=z",
            "headers": {
                "Authorization": "Bearer <LOCAL_TOKEN>",
                "pp-deviceid": "device-123",
                "pp-time": "1234567890123",
                "pp-seqid": "seq-123",
                "seal-v3": "seal-real-value",
                "sign-v3": "sign-real-value",
            },
        },
    }


def test_normalize_hook_request_extracts_path_query_and_headers() -> None:
    normalized = normalize_hook_request(sample_hook_event())

    assert normalized["method"] == "GET"
    assert normalized["path"] == "/client/product/storeproduct/detail_popup/s/p"
    assert normalized["query"] == [["zip", "z"]]
    assert normalized["headers"]["authorization"] == "Bearer <LOCAL_TOKEN>"
    assert normalized["headers"]["seal-v3"] == "seal-real-value"


def test_signature_cache_entry_keeps_signed_headers_only() -> None:
    entry = signature_cache_entry_from_hook_event(sample_hook_event())

    assert entry["request_fingerprint"].startswith("sha256:")
    assert entry["signed_headers"] == {
        "pp-time": "1234567890123",
        "pp-seqid": "seq-123",
        "seal-v3": "seal-real-value",
        "sign-v3": "sign-real-value",
    }
    assert entry["metadata"]["hook"] == "okhttp3.internal.http.RealInterceptorChain.proceed"


def test_upsert_signature_cache_entry_replaces_same_fingerprint() -> None:
    first = signature_cache_entry_from_hook_event(sample_hook_event())
    second = dict(first)
    second["signed_headers"] = {"seal-v3": "replacement-seal"}
    cache: dict[str, object] = {"schema_version": 1, "entries": []}

    upsert_signature_cache_entry(cache, first)
    upsert_signature_cache_entry(cache, second)

    assert len(cache["entries"]) == 1
    assert cache["entries"][0]["signed_headers"] == {"seal-v3": "replacement-seal"}


def test_redact_hook_event_for_log_masks_credentials_and_signatures() -> None:
    redacted = redact_hook_event_for_log(sample_hook_event())
    serialized = json.dumps(redacted, ensure_ascii=False)

    assert "<LOCAL_TOKEN>" not in serialized
    assert "seal-real-value" not in serialized
    assert "sign-real-value" not in serialized
    assert "1234567890123" not in serialized
    assert "<REDACTED_SHA256:" in serialized
    assert "<SIGNATURE_SHA256:" in serialized


def test_cache_to_json_writes_parseable_json(tmp_path: Path) -> None:
    entry = signature_cache_entry_from_hook_event(sample_hook_event())
    cache = upsert_signature_cache_entry({"schema_version": 1, "entries": []}, entry)
    path = tmp_path / "cache.json"
    path.write_text(cache_to_json(cache), encoding="utf-8")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["entries"][0]["request_fingerprint"] == entry["request_fingerprint"]
