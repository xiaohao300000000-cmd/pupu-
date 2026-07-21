# Pupu Frida hook capture workflow - 2026-07-22

This is the dynamic route for recovering usable `seal/sign` evidence when static SecNeo unpacking is blocked.

## Added files

- `scripts/frida/pupu_sign_capture.js`
  - observes `okhttp3.Request$Builder.build`;
  - observes `okhttp3.internal.http.RealInterceptorChain.proceed`;
  - probes known sign-related classes:
    - `com.pupumall.adkx.http.interceptor.HeaderSignInterceptor`
    - `com.pupumall.adkx.http.interceptor.TrackableHeaderSignInterceptor`
    - `com.pupumall.customer.tinystack.MNetSecurityUtil`
  - sends structured Frida events to the Python runner;
  - does not alter requests or patch transport behavior.
- `scripts/capture_pupu_signatures.py`
  - attaches/spawns the local Android app through Frida;
  - writes redacted event logs to `.local/evidence/pupu-frida-events.redacted.jsonl`;
  - writes exact-match signed-header cache entries to `.local/private/pupusgn-signature-cache.json`;
  - stdout prints only count, fingerprint, and file path; it does not print real `seal/sign` values.
- `scripts/frida/pupu_dex_dump.js` and `scripts/dump_pupu_dex.py`
  - native-only early Frida script;
  - does not require `Java.perform()`;
  - scans readable memory for DEX/CDex magic;
  - writes dumps only to ignored `.local/evidence/dex-dumps/`.
- `src/pupu_assistant/integrations/pupu/hook_capture.py`
  - normalizes hook events;
  - extracts signed headers;
  - computes `pupusgn` request fingerprints;
  - redacts logs.

## Run

Device state is required. On the current machine, `adb devices -l` returned no devices during this update, so live capture was not executed.

When an authorized phone/emulator is connected:

```powershell
adb devices -l
frida-ps -U
py -3.12 scripts/capture_pupu_signatures.py
```

If the app is already running:

```powershell
py -3.12 scripts/capture_pupu_signatures.py --attach
```

For non-interactive emulator runs:

```powershell
py -3.12 scripts/capture_pupu_signatures.py --duration 30
py -3.12 scripts/capture_pupu_signatures.py --attach --duration 30
```

Then exercise a low-risk product detail request in the app. For cart-related captures, use preview/read flows first; avoid writing the real cart until the normal confirmation/readback state machine is connected.

## Use captured signatures with pupusgn

```powershell
py -3.12 .local/bin/pupusgn `
  --input .local/pupusgn-sdu-input.json `
  --case sdu_product_detail_popup `
  --signature-cache .local/private/pupusgn-signature-cache.json `
  --pretty
```

Cache entries are exact-match. If method/path/query/body hash/header context changes, the cache misses and `pupusgn` fails closed.

## Reverse-engineering loop after capture

1. Collect several signed product-detail events and one non-mutating cart/read event.
2. Compare normalized requests and signed headers:
   - what changes with timestamp;
   - what changes with path/query;
   - whether `seal-v3` and `sign-v3` are both present;
   - whether `MNetSecurityUtil` logs reveal a preimage string or helper return.
3. If real classes materialize after SecNeo load, dump class/method names around:
   - `HeaderSignInterceptor`
   - `TrackableHeaderSignInterceptor`
   - `MNetSecurityUtil`
4. Only after fixed input/output vectors exist, implement a real local algorithm and keep the protected request service fail-closed until those vectors pass.

## Emulator attempt on 2026-07-22

This is a real alternative to connecting a physical phone, and it was tested locally.

Observed local emulator assets:

- emulator binary: `C:\Users\10579\codex-tools\android-sdk\emulator\emulator.exe`
- x86_64 AVD: `codex-pupu-api35`
- arm64 AVD config: `codex-pupu-api35-arm64`

Results:

1. `codex-pupu-api35` boots and `adb root` works.
2. The original 6.4.9 APK installs, but crashes on startup because SecNeo selects `libDexHelper-x86.so`, which is not packaged.
3. A local test build was rebuilt in ignored `.local/private/` with `com/secneo/apkwrapper/H.smali` patched from `DexHelper-x86` to `DexHelper`.
4. The patched APK was v2/v3 signed and installed successfully.
5. The patched APK gets past the missing-x86-library failure and loads `/lib/arm64/libDexHelper.so`.
6. It then hits native `SIGSEGV` inside/after `libDexHelper.so` initialization under the x86_64 emulator's arm64 native bridge.
7. The `codex-pupu-api35-arm64` AVD did not come online in the local Windows emulator within a three-minute boot window.
8. A native-only early DEX memory dump script was added and tested against the patched x86_64 emulator run.
   - Result: no DEX dump yet.
   - Evidence: script reached `initial_250ms` scan, then the app exited/crashed before later scans.
   - Interpretation: for this x86_64/native-bridge path, the next hook point needs to move lower into native allocation/copy/mmap or SecNeo loader internals rather than relying on post-load DEX magic scanning.

Current interpretation:

- physical phone is not the only route;
- x86_64 emulator route is partially working but blocked by SecNeo/native-bridge crash;
- a real arm64 Android runtime remains the most reliable dynamic route: phone, working arm64 emulator, WSA/third-party emulator with ARM support, or cloud device.

Other non-phone paths still open:

1. Install/use an ARM-capable Android runtime on this PC:
   - WSA if available;
   - BlueStacks/MuMu/LDPlayer/Nox with ARM translation;
   - Genymotion/cloud ARM device.
2. Continue static SecNeo unpacking from `classes.dex` `dexdata0`/`fdex`.
3. Continue native-assisted dump:
   - hook `mmap`, `mprotect`, `memcpy`, `openat/read`, and DexFile loader entry points;
   - instrument `libDexHelper.so` before the crashing basic block;
   - dump candidate buffers before they are registered with ART.
