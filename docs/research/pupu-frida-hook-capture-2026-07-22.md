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

