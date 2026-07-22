# Pupu libmixmaster.so unidbg smoke harness (2026-07-22)

## Current result

This follow-up removes one major blocker in the no-phone path: on local Windows + unidbg, `libmixmaster.so` can now be loaded and `com.pupumall.tinystack.Vortex.swindle(...)` can be invoked.

Verified facts:

- `JNI_OnLoad` runs under unidbg and registers:
  - `thrust(Landroid/content/Context;)V` -> native offset `0x343d8`
  - `swindle(Landroid/content/Context;IILjava/util/HashMap;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;` -> native offset `0x35ac4`
- `swindle` reads the complete header map via `entrySet/iterator/hasNext/next/getKey/getValue`.
- `swindle` reads the request path and device-feed string.
- With synthetic header/path/feed input, `swindle` returns a JSON-shaped value with `s0/s1/s2/s3`; the main payload is in `s2`.
- The reusable signer mode now computes `sign-v3` from the same canonical header format recovered from `com.pupumall.customer.tinystack.z` and passes only `timestamp + sign-v3` into `Vortex.swindle(...)`, matching the recovered `MNetSecurityUtil` request boundary.

No real account, token, SMS code, captured request header, or real production seal/sign value is stored or committed.

## Added files

- `scripts/unidbg/PupuMixmasterHarness.java`
  - Copy this into a private unidbg checkout under `unidbg-android/src/test/java/com/pupu/harness/`.
  - Includes minimal Android/JNI stubs for `libandroid.so` sensor/looper calls, `libmediandk.so` DRM calls, `ActivityThread.currentApplication()`, `Application.getFilesDir()`, and Java map iteration.
  - In `--signer` mode, reads stdin JSON through the runner, derives `sign-v3`, calls native `swindle`, and emits `signed_headers.sign-v3` plus `signed_headers.seal-v3`.
- `scripts/run_pupu_mixmaster_harness.ps1`
  - Copies the harness into the private unidbg checkout and runs it.
- `scripts/validate_pupu_protected.py`
  - Reads `.local/private/pupu-live-request.json` (private, not committed), tries `seal-v3` in `full` and `s2` modes, runs one protected request, and writes redacted evidence to `.local/evidence/protected-live-validation.json`.
- `.local/pupu-live-request.example.json`
  - Commit-safe template for the private live request file. Replace placeholders locally only.

Default local command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pupu_mixmaster_harness.ps1
```

Override paths if needed:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pupu_mixmaster_harness.ps1 `
  -UnidbgRoot ".local/private/unidbg-work/unidbg" `
  -LibMixmaster "../artifacts/apk/pupu-6.4.9-downkuai-apktool/lib/arm64-v8a/libmixmaster.so" `
  -Path "/client/product/storeproduct/detail" `
  -DeviceFeed "{}"
```

## Private unidbg build fixes

Java 21 conflicts with unidbg's `com.github.unidbg.Module` because `java.lang.Module` also exists. The private checkout was patched with explicit imports in:

- `unidbg-api/.../AbstractARMDebugger.java`
- `unidbg-android/.../AndroidElfLoader.java`

Build/install command used locally:

```powershell
.\mvnw.cmd -s .mvn\local-settings.xml -pl unidbg-android -am `
  -DskipTests "-Dmaven.javadoc.skip=true" "-Dgpg.skip=true" install
```

The harness also needs Java 21 reflective access to `java.util`:

```powershell
$env:MAVEN_OPTS='--add-opens java.base/java.util=ALL-UNNAMED'
```

The runner script sets this automatically.

## Remaining gap to the main goal

The gap has narrowed from "native code cannot run locally" to "validate service acceptance with authorized live request context":

1. Run `scripts/validate_pupu_protected.py` with an authorized private request file and confirm whether `full` or `s2` is the accepted `seal-v3` format.
2. Confirm which caller path always provides `timestamp` versus older local fixtures that used `pp-time`; signer mode accepts either and emits `timestamp`.
3. Continue Android environment stubs in `thrust` only if stricter device context is required by live validation.
4. Handle `libwindcharger.so` / `Gears` legacy `seal/sign-v2` separately; it still looks more packed/self-decrypting and is better handled with dynamic dump first.

## Hygiene

- APKs, DEXes, unidbg checkout, run outputs, and real request samples stay in `.local/` or `../artifacts/` and are not committed.
- The committed harness uses synthetic `pp-time/pp-seqid/user-agent` values only. It verifies the native execution chain; it is not a production request vector.
