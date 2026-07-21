# Pupu SecNeo static unpack follow-up - 2026-07-22

## Current result

Static unpacking is now reproducible without a phone:

```powershell
py -3.12 -m pip install zstandard gmssl
py -3.12 scripts/unpack_secneo_pupu_dex.py `
  --classes-dex C:\Users\10579\work\pupu-audit\artifacts\extract649\classes.dex `
  --out .local\evidence\secneo-decrypted

py -3.12 scripts/fix_secneo_stolen_code.py `
  --input .local\evidence\secneo-decrypted `
  --out .local\evidence\secneo-fixed-v2
```

Generated DEX files and JADX output stay under ignored `.local/evidence/`.

## Recovered payload facts

- `dexdata0` marker: `0x9168`
- copied prefix length: `0x02d4e000`
- zstd compressed length: `0x005c8ab1`
- zstd output length: `0x01e00000`
- derived SM4 key scheme: hardcoded 16-byte mask XOR package-name first 16 bytes
- DEX count: 9, written as `classes2.dex` through `classes10.dex`
- first `0x20000` bytes of each logical DEX are SM4-ECB encrypted, no padding
- stolen code pool marker: `BBbb.dgc`
- DGC record size: `0x18`
- repaired stolen-code counts:
  - classes2: `10508`
  - classes3: `2034`
  - classes4: `5346`
  - classes5: `5860`
  - classes6: `5236`
  - classes7: `6671`
  - classes8: `637`
  - classes9: `402`
  - classes10: `504`

## Sign/seal boundary

The Java request-building path is recovered, but the cryptographic/signing cores are native:

- `com.pupumall.tinystack.Gears`
  - `drift(Context, String)` is native
  - `blurr(Context, String)` is native
  - loads `libwindcharger.so`
- `com.pupumall.tinystack.Vortex`
  - `swindle(Context, int, int, HashMap<String,String>, String, String)` is native
  - `thrust(Context)` is native
  - loads `libmixmaster.so`
- `com.pupumall.customer.tinystack.z`
  - canonicalizes sorted key/value bytes in Java
  - final `c(...)` / `d(...)` derivation calls are routed through `com.fort.andjni.JniLib`

Important request logic already visible:

- `MNetSecurityUtil.z(request)` builds `sign-v3` from sorted request headers via `z.c(new z.a().g(map).c())`.
- It then computes `seal-v3` with `Vortex.swindle(...)` using timestamp/sign map, request path, device fingerprint material, and request type flags.
- Legacy `sign-v2` / `seal` paths use `Gears.drift(...)` / `Gears.blurr(...)`.

So the remaining "real sign/seal" blocker is not Java routing anymore; it is native recovery for:

- `libwindcharger.so`
- `libmixmaster.so`
- AndJni-dispatched `JniLib` methods used by `z`

## Added native mapping helper

`scripts/frida/pupu_register_natives_trace.js` traces JNI `RegisterNatives` mappings and reports:

- Java class name
- native method name/signature
- function pointer
- containing module and module offset

This is intended for the next dynamic run on a device/runtime that gets past SecNeo startup. It writes only runtime mapping events; do not commit captures.

## What this means

The emulator-only path still cannot finish real runtime signing on this Windows x86_64 host because the app crashes under ARM native bridge after SecNeo/native startup. The static path did succeed far enough to recover the Java request flow and exact native libraries. The next productive work item is native analysis or a successful `RegisterNatives` capture, not more Java grep.
