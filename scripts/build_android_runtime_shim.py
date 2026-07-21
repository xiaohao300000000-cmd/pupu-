from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "native-shims" / "android_runtime_file_descriptor_shim.c"


def find_ndk(explicit: str | None) -> Path:
    if explicit:
        ndk = Path(explicit)
        if ndk.exists():
            return ndk
        raise SystemExit(f"NDK path does not exist: {ndk}")

    candidates: list[Path] = []
    for key in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT"):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value))

    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        ndk_dir = Path(sdk) / "ndk"
        if ndk_dir.exists():
            candidates.extend(sorted(ndk_dir.iterdir(), reverse=True))

    user_sdk = Path.home() / "codex-tools" / "android-sdk" / "ndk"
    if user_sdk.exists():
        candidates.extend(sorted(user_sdk.iterdir(), reverse=True))

    for candidate in candidates:
        clang = (
            candidate
            / "toolchains"
            / "llvm"
            / "prebuilt"
            / "windows-x86_64"
            / "bin"
            / "aarch64-linux-android35-clang.cmd"
        )
        if clang.exists():
            return candidate

    raise SystemExit(
        'Android NDK not found; install one with sdkmanager --install "ndk;28.2.13676358"'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the arm64 libandroid_runtime.so shim.")
    parser.add_argument("--ndk", help="Android NDK root")
    parser.add_argument("--api", type=int, default=35)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", required=True, help="Output libandroid_runtime.so path")
    args = parser.parse_args()

    ndk = find_ndk(args.ndk)
    clang = (
        ndk
        / "toolchains"
        / "llvm"
        / "prebuilt"
        / "windows-x86_64"
        / "bin"
        / f"aarch64-linux-android{args.api}-clang.cmd"
    )
    if not clang.exists():
        raise SystemExit(f"Compiler not found: {clang}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(clang),
        "-shared",
        "-fPIC",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Wl,-soname,libandroid_runtime.so",
        "-o",
        str(out),
        str(Path(args.source)),
    ]
    subprocess.run(cmd, check=True)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
