from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pupu_assistant.integrations.pupu.hook_capture import (  # noqa: E402
    cache_to_json,
    redact_hook_event_for_log,
    signature_cache_entry_from_hook_event,
    upsert_signature_cache_entry,
)

DEFAULT_PACKAGE = "com.pupumall.customer"
DEFAULT_SCRIPT = REPO_ROOT / "scripts" / "frida" / "pupu_sign_capture.js"
DEFAULT_EVENTS = REPO_ROOT / ".local" / "evidence" / "pupu-frida-events.redacted.jsonl"
DEFAULT_CACHE = REPO_ROOT / ".local" / "private" / "pupusgn-signature-cache.json"


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "description": "Private exact-match cache generated from local Frida captures.",
            "entries": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cache file must contain a JSON object")
    return data


def write_json(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run_capture(args: argparse.Namespace) -> int:
    try:
        import frida
    except ImportError:
        print("frida Python package not installed; install frida-tools first", file=sys.stderr)
        return 2

    script_source = Path(args.script).read_text(encoding="utf-8")
    cache_path = Path(args.cache)
    events_path = Path(args.events)
    cache = load_cache(cache_path)
    captured_count = 0

    def on_message(message: dict[str, Any], data: bytes | None) -> None:
        del data
        nonlocal captured_count, cache
        if message.get("type") != "send":
            print(json.dumps({"frida": message}, ensure_ascii=False), file=sys.stderr)
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        append_jsonl(events_path, redact_hook_event_for_log(payload))
        try:
            entry = signature_cache_entry_from_hook_event(payload)
        except Exception:
            return
        cache = upsert_signature_cache_entry(cache, entry)
        write_json(cache_path, cache_to_json(cache))
        captured_count += 1
        print(
            json.dumps(
                {
                    "captured": captured_count,
                    "fingerprint": entry["request_fingerprint"],
                    "signed_header_count": len(entry["signed_headers"]),
                    "cache": str(cache_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    try:
        device = frida.get_usb_device(timeout=args.timeout)
        if args.attach:
            session = device.attach(args.package)
            pid = None
        else:
            pid = device.spawn([args.package])
            session = device.attach(pid)
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "frida_device_or_process_unavailable",
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    script = session.create_script(script_source)
    script.on("message", on_message)
    script.load()
    if pid is not None:
        device.resume(pid)

    print(
        json.dumps(
            {
                "status": "capturing",
                "package": args.package,
                "events": str(events_path),
                "cache": str(cache_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass
    finally:
        session.detach()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture Pupu signed request headers through a local Frida session."
    )
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--script", default=str(DEFAULT_SCRIPT))
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--attach", action="store_true", help="attach to a running process")
    return run_capture(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
