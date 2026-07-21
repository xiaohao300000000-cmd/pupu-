from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

import zstandard as zstd
from gmssl.func import bytes_to_list, list_to_bytes
from gmssl.sm4 import SM4_DECRYPT, CryptSM4

DEXDATA_MAGIC = b"dexdata0"
TAIL_MARKER = b"BBbb.dgc"
DEFAULT_PACKAGE = "com.pupumall.customer"
DEFAULT_KEY_MASK = bytes.fromhex("66 97 6c e8 6d 46 38 b0 09 5a a5 d7 0f cb 9a a0")
DEFAULT_OUT = Path(".local/evidence/secneo-decrypted")


@dataclass(frozen=True)
class DexEntry:
    name: str
    source_offset: str
    file_size: str
    tail_marker_offset: str
    end_delta_from_tail: str
    sha256: str | None = None


def derive_key(package_name: str, mask: bytes) -> bytes:
    package = package_name.encode("utf-8")
    if len(package) < 16:
        raise SystemExit(
            "Package name must be at least 16 bytes for this SecNeo key scheme: "
            f"{package_name}"
        )
    return bytes(a ^ b for a, b in zip(mask, package[:16], strict=True))


def sm4_decrypt_ecb_no_padding(data: bytes, key: bytes) -> bytes:
    if len(data) % 16:
        raise ValueError("SM4 ECB input must be 16-byte aligned")
    cipher = CryptSM4()
    cipher.set_key(key, SM4_DECRYPT)
    output: list[int] = []
    for offset in range(0, len(data), 16):
        output += cipher.one_round(cipher.sk, bytes_to_list(data[offset : offset + 16]))
    return list_to_bytes(output)


def parse_secneo_payload(data: bytes) -> tuple[int, int, int, int]:
    marker = data.find(DEXDATA_MAGIC)
    if marker < 0:
        raise SystemExit("dexdata0 marker not found")
    copy_len = int.from_bytes(data[marker + 0x0C : marker + 0x10], "big")
    zstd_len = int.from_bytes(data[marker + 0x10 : marker + 0x14], "big")
    zstd_out_len = int.from_bytes(data[marker + 0x14 : marker + 0x18], "big")
    if copy_len <= 0 or zstd_len <= 0 or zstd_out_len <= 0:
        raise SystemExit("Invalid dexdata0 header lengths")
    return marker, copy_len, zstd_len, zstd_out_len


def build_merged_payload(
    data: bytes,
    marker: int,
    copy_len: int,
    zstd_len: int,
    zstd_out_len: int,
) -> bytes:
    # This SecNeo build stores the compressed frame after the copied prefix, at the
    # same relative marker+0x18 offset used by the header inside the copied prefix.
    compressed_offset = copy_len + marker + 0x18
    compressed = data[compressed_offset : compressed_offset + zstd_len]
    if len(compressed) != zstd_len:
        raise SystemExit("Truncated zstd payload")
    decompressed = zstd.ZstdDecompressor().stream_reader(BytesIO(compressed)).read(zstd_out_len)
    if len(decompressed) != zstd_out_len:
        raise SystemExit(f"Unexpected zstd output length: {len(decompressed)} != {zstd_out_len}")
    return data[:copy_len] + decompressed


def find_tail_markers(merged: bytes) -> list[int]:
    markers: list[int] = []
    cursor = 0
    while True:
        index = merged.find(TAIL_MARKER, cursor)
        if index < 0:
            break
        markers.append(index)
        cursor = index + 1
    if not markers:
        raise SystemExit("No BBbb.dgc tail markers found")
    return markers


def dex_header_at(merged: bytes, offset: int, key: bytes) -> tuple[bytes, int] | None:
    encrypted = merged[offset : offset + 0x70]
    if len(encrypted) < 0x70:
        return None
    header = sm4_decrypt_ecb_no_padding(encrypted, key)
    if header[:4] != b"dex\n" or header[4:7] not in {b"035", b"037", b"038"}:
        return None
    file_size = int.from_bytes(header[0x20:0x24], "little")
    if not 0x70 <= file_size <= len(merged) - offset:
        return None
    return header, file_size


def find_dex_entries(
    merged: bytes,
    dexdata_offset: int,
    key: bytes,
) -> list[tuple[int, int, int, int]]:
    markers = find_tail_markers(merged)
    entries: list[tuple[int, int, int, int]] = []
    for index, tail in enumerate(markers):
        if index == 0:
            start = dexdata_offset + 0x800
            stop = dexdata_offset + 0x3000
        else:
            start = markers[index - 1] + 0x10
            stop = min(tail, start + 0x10000)

        found: tuple[int, int, int, int] | None = None
        for candidate in range((start + 15) // 16 * 16, stop, 16):
            parsed = dex_header_at(merged, candidate, key)
            if parsed is None:
                continue
            _, file_size = parsed
            delta = candidate + file_size - tail
            # Most DEXes end just after the BBbb.dgc/fdex tail. One observed Pupu
            # DEX has extra slack after the tail; keep it because the header's
            # file_size is what dalvik/jadx expects.
            if -0x100 <= delta <= 0x30000:
                logical_offset = candidate
                if delta > 0x100:
                    # One Pupu 6.4.9 DEX has its encrypted first 0x20000-byte
                    # window shifted forward, while the logical DEX tail still
                    # lives at the earlier offset. Derive the logical offset
                    # from the tail position and DEX header file_size.
                    logical_offset = candidate - (delta - 0x13)
                found = candidate, logical_offset, file_size, delta
                break
        if found is None:
            raise SystemExit(
                "Unable to locate encrypted DEX header before tail marker "
                f"{index}: 0x{tail:x}"
            )
        entries.append(found)
    return entries


def decrypt_dex_chunk(
    merged: bytes, encrypted_offset: int, logical_offset: int, file_size: int, key: bytes
) -> bytes:
    chunk = bytearray(merged[logical_offset : logical_offset + file_size])
    # Pupu 6.4.9 classes5 has a SecNeo overlap anomaly: the DEX prefix is
    # sourced from the shifted encrypted window, then the tail comes from the
    # logical stream so the BBbb.dgc block remains at the file end.
    if encrypted_offset - logical_offset == 0x9180 and file_size == 0x8D08AB:
        split = 0x71D24D
        chunk[:split] = merged[encrypted_offset : encrypted_offset + split]
    encrypted_len = min(0x20000, len(chunk))
    encrypted_len -= encrypted_len % 16
    encrypted_prefix = merged[encrypted_offset : encrypted_offset + encrypted_len]
    chunk[:encrypted_len] = sm4_decrypt_ecb_no_padding(bytes(encrypted_prefix), key)
    return bytes(chunk)


def run(args: argparse.Namespace) -> int:
    source = Path(args.classes_dex)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    marker, copy_len, zstd_len, zstd_out_len = parse_secneo_payload(data)
    key = bytes.fromhex(args.key) if args.key else derive_key(args.package, DEFAULT_KEY_MASK)
    merged = build_merged_payload(data, marker, copy_len, zstd_len, zstd_out_len)
    entries = find_dex_entries(merged, marker, key)

    manifest: dict[str, object] = {
        "source": str(source),
        "dexdata_offset": f"0x{marker:x}",
        "copy_len": f"0x{copy_len:x}",
        "zstd_len": f"0x{zstd_len:x}",
        "zstd_out_len": f"0x{zstd_out_len:x}",
        "package": args.package,
        "sm4_key_hex": key.hex() if args.print_key else "<redacted>",
        "entries": [],
    }

    import hashlib

    for dex_number, (encrypted_offset, logical_offset, file_size, delta) in enumerate(
        entries,
        start=2,
    ):
        chunk = decrypt_dex_chunk(merged, encrypted_offset, logical_offset, file_size, key)
        name = f"classes{dex_number}.dex"
        path = out_dir / name
        path.write_bytes(chunk)
        digest = hashlib.sha256(chunk).hexdigest()
        entry = DexEntry(
            name=name,
            source_offset=f"0x{logical_offset:x}",
            file_size=f"0x{file_size:x}",
            tail_marker_offset=f"0x{chunk.find(TAIL_MARKER):x}",
            end_delta_from_tail=f"0x{delta:x}",
            sha256=digest,
        )
        entry_dict = asdict(entry)
        entry_dict["encrypted_prefix_offset"] = f"0x{encrypted_offset:x}"
        manifest["entries"].append(entry_dict)
        print(
            f"{name}: offset=0x{logical_offset:x} "
            f"encrypted_prefix=0x{encrypted_offset:x} size=0x{file_size:x} sha256={digest}"
        )

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unpack Pupu's SecNeo dexdata0 payload into decrypted DEX files."
    )
    parser.add_argument("--classes-dex", required=True, help="Original protected classes.dex")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output directory for decrypted DEX files",
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help="Android package name used for key derivation",
    )
    parser.add_argument("--key", help="Override SM4 key hex")
    parser.add_argument(
        "--print-key",
        action="store_true",
        help="Include derived key in manifest for local evidence",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
