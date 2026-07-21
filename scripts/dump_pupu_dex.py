from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_PACKAGE = "com.pupumall.customer"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = REPO_ROOT / "scripts" / "frida" / "pupu_dex_dump.js"
DEFAULT_OUT = REPO_ROOT / ".local" / "evidence" / "dex-dumps"


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def run(args: argparse.Namespace) -> int:
    try:
        import frida
    except ImportError:
        print("frida Python package not installed; install frida-tools first", file=sys.stderr)
        return 2

    script_source = Path(args.script).read_text(encoding="utf-8")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"
    dump_count = 0

    def on_message(message: dict[str, Any], data: bytes | None) -> None:
        nonlocal dump_count
        payload = message.get("payload")
        if message.get("type") != "send" or not isinstance(payload, dict):
            write_jsonl(events_path, {"frida": message})
            return
        if payload.get("kind") == "dex_dump" and data:
            digest = hashlib.sha256(data).hexdigest()
            suffix = str(payload.get("magic") or "dex").replace("/", "_")
            path = out_dir / f"{dump_count:03d}-{digest[:16]}-{suffix}.dex"
            path.write_bytes(data)
            payload = dict(payload)
            payload["sha256"] = digest
            payload["dump_path"] = str(path)
            dump_count += 1
            print(
                json.dumps(
                    {
                        "dumped": dump_count,
                        "path": str(path),
                        "sha256": digest,
                        "size": len(data),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        write_jsonl(events_path, payload)

    try:
        device = frida.get_usb_device(timeout=args.timeout)
        if args.attach:
            process = device.get_process(args.package)
            session = device.attach(process.pid)
            pid = None
        else:
            pid = device.spawn([args.package])
            session = device.attach(pid)
    except Exception as error:
        print(
            json.dumps(
                {"ok": False, "error": "frida_unavailable", "message": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    script = session.create_script(script_source, runtime="v8")
    script.on("message", on_message)
    script.load()
    if pid is not None:
        device.resume(pid)
    print(
        json.dumps(
            {
                "status": "dumping",
                "package": args.package,
                "out": str(out_dir),
                "events": str(events_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    try:
        time.sleep(args.duration)
    finally:
        session.detach()
    print(json.dumps({"dump_count": dump_count, "out": str(out_dir)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dump Pupu DEX-like memory through Frida.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--script", default=str(DEFAULT_SCRIPT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--duration", type=int, default=8)
    parser.add_argument("--attach", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
