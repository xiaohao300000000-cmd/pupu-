from __future__ import annotations

import argparse
import hashlib
import json
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

TAIL_MARKER = b"BBbb.dgc"
DEFAULT_IN = Path(".local/evidence/secneo-decrypted")
DEFAULT_OUT = Path(".local/evidence/secneo-fixed-v2")


@dataclass(frozen=True)
class FixResult:
    name: str
    patched_methods: int
    dgc_offset: str
    dgc_size: str
    record_size: int
    record_bytes: str
    code_base: str
    sha256: str


def read_u16(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_u32(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_be32(data: bytes | bytearray, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def read_uleb128(data: bytes | bytearray, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    cursor = offset
    while True:
        value = data[cursor]
        cursor += 1
        result |= (value & 0x7F) << shift
        if value & 0x80 == 0:
            return result, cursor
        shift += 7
        if shift > 35:
            raise ValueError(f"uleb128 too large at 0x{offset:x}")


def iter_code_offsets(data: bytes | bytearray) -> list[int]:
    class_defs_size = read_u32(data, 0x60)
    class_defs_off = read_u32(data, 0x64)
    offsets: list[int] = []
    for class_index in range(class_defs_size):
        class_def = class_defs_off + class_index * 0x20
        class_data_off = read_u32(data, class_def + 0x18)
        if class_data_off == 0:
            continue
        cursor = class_data_off
        static_fields_size, cursor = read_uleb128(data, cursor)
        instance_fields_size, cursor = read_uleb128(data, cursor)
        direct_methods_size, cursor = read_uleb128(data, cursor)
        virtual_methods_size, cursor = read_uleb128(data, cursor)
        for _ in range(static_fields_size + instance_fields_size):
            _, cursor = read_uleb128(data, cursor)  # field_idx_diff
            _, cursor = read_uleb128(data, cursor)  # access_flags
        for _ in range(direct_methods_size + virtual_methods_size):
            _, cursor = read_uleb128(data, cursor)  # method_idx_diff
            _, cursor = read_uleb128(data, cursor)  # access_flags
            code_off, cursor = read_uleb128(data, cursor)
            if code_off:
                offsets.append(code_off)
    return offsets


def build_debug_info_index(data: bytes | bytearray) -> dict[int, list[int]]:
    by_debug: dict[int, list[int]] = {}
    for code_off in iter_code_offsets(data):
        if code_off + 16 > len(data):
            continue
        registers_size = read_u16(data, code_off)
        ins_size = read_u16(data, code_off + 2)
        outs_size = read_u16(data, code_off + 4)
        debug_info_off = read_u32(data, code_off + 8)
        insns_size = read_u32(data, code_off + 12)
        if registers_size == 0 and ins_size == 0 and outs_size == 0:
            continue
        if insns_size == 0 or code_off + 16 + insns_size * 2 > len(data):
            continue
        by_debug.setdefault(debug_info_off, []).append(code_off)
    return by_debug


def repair_dex_header(data: bytearray) -> None:
    data[12:32] = hashlib.sha1(data[32:]).digest()
    data[8:12] = (zlib.adler32(data[12:]) & 0xFFFFFFFF).to_bytes(4, "little")


def fix_one(path: Path, out_dir: Path) -> FixResult:
    data = bytearray(path.read_bytes())
    marker = data.find(TAIL_MARKER)
    if marker < 0:
        raise SystemExit(f"{path}: BBbb.dgc marker not found")
    dgc_size = read_be32(data, marker - 4)
    dgc_start = marker - 0x20 - dgc_size
    if dgc_start < 0 or dgc_start + dgc_size > len(data):
        raise SystemExit(f"{path}: invalid DGC bounds")

    record_size = read_be32(data, dgc_start + 8)
    record_bytes = read_be32(data, dgc_start + 12)
    code_base = read_be32(data, dgc_start + 16)
    if record_size < 0x18 or record_bytes % record_size:
        raise SystemExit(f"{path}: unexpected DGC record layout")

    by_debug = build_debug_info_index(data)
    patched = 0
    # DGC header layout in this SecNeo build:
    #   +0x00 be32 dgc_size
    #   +0x04 magic ab ba cd dc
    #   +0x08 be32 record_size (0x18)
    #   +0x0c be32 record table byte length
    #   +0x10 be32 code blob base, relative to DGC start
    #   +0x14 be32 code blob byte length
    # Records start at +0x18. The first two be32 fields are code offset
    # (relative to code_base) and full code_item size.
    records_start = dgc_start + 0x18
    records_end = min(records_start + record_bytes, dgc_start + code_base, dgc_start + dgc_size)
    for cursor in range(records_start, records_end, record_size):
        code_rel = read_be32(data, cursor)
        full_size = read_be32(data, cursor + 4)
        code_abs = dgc_start + code_base + code_rel
        if full_size < 16 or code_abs + full_size > len(data):
            continue
        debug_info_off = read_u32(data, code_abs + 8)
        if debug_info_off == 0:
            continue
        candidates = by_debug.get(debug_info_off)
        if not candidates:
            continue
        target = candidates.pop(0)
        if target + full_size > len(data):
            continue
        data[target : target + full_size] = data[code_abs : code_abs + full_size]
        patched += 1

    repair_dex_header(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / path.name
    out_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"{path.name}: patched={patched} sha256={digest}")
    return FixResult(
        name=path.name,
        patched_methods=patched,
        dgc_offset=f"0x{dgc_start:x}",
        dgc_size=f"0x{dgc_size:x}",
        record_size=record_size,
        record_bytes=f"0x{record_bytes:x}",
        code_base=f"0x{code_base:x}",
        sha256=digest,
    )


def run(args: argparse.Namespace) -> int:
    in_dir = Path(args.input)
    out_dir = Path(args.out)
    paths = sorted(in_dir.glob("classes*.dex"), key=lambda p: (len(p.stem), p.stem))
    if not paths:
        raise SystemExit(f"No classes*.dex files found in {in_dir}")
    results = [fix_one(path, out_dir) for path in paths]
    manifest = {
        "input": str(in_dir),
        "output": str(out_dir),
        "results": [asdict(r) for r in results],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore SecNeo stolen code_items from BBbb.dgc tails."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_IN),
        help="Directory containing decrypted classes*.dex",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output directory for fixed DEX files",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
