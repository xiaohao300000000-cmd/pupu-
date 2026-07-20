# Pupu Signature and Real Cart Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production change follows superpowers:test-driven-development. Do not call a cart mutation endpoint until the preview has been explicitly confirmed.

**Goal:** Build and prove the vertical slice `business module → PupuSignatureService → PupuHttpClient → Pupu API`, then use it to add one explicitly selected item to the user's real Pupu cart and verify the cart by reading it back.

**Architecture:** A Python 3.12 package will isolate request normalization and signing from transport and business modules. Public endpoints use an explicit `none` signature result; protected endpoints fail closed until a currently valid algorithm is reconstructed from the latest official client or a user-owned request trace. Cart changes use preview-confirm-execute-verify and never create an order or payment.

**Tech Stack:** Python 3.12, `httpx`, `pydantic`, `pydantic-settings`, `typer`, `pytest`, `pytest-asyncio`, `respx`, standard-library `hashlib`/`base64`/`secrets`, and a vetted XXTEA implementation only if current-client evidence confirms it.

---

## Non-negotiable acceptance gates

- No Pupu business module imports or instantiates `httpx`, `requests`, `aiohttp`, or a raw network session.
- Every request, including public server-time requests, is passed to `PupuSignatureService`.
- Protected requests fail before network I/O when no verified signer is available.
- Mock and recorded responses are allowed for unit/contract tests, but are never listed as live validation.
- Live evidence records endpoint path, signature mode, time, HTTP/API result, response shape, and mobile-app verification without secrets or personal data.
- A successful mutation requires both a successful Pupu response and a subsequent cart read containing the expected product and quantity.
- No order creation, checkout, payment, address modification, coupon consumption, lottery, exchange, or card synthesis is part of this plan.

## Task 1: Create the Python package and safety boundary

**Files:**

- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/pupu_assistant/__init__.py`
- Create: `src/pupu_assistant/config.py`
- Create: `tests/test_config.py`

**Step 1: Create and activate the isolated environment**

Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
```

Expected: `.venv/bin/python --version` reports Python 3.12.

**Step 2: Write the failing configuration test**

The test must prove:

- secrets are optional at import time;
- `PUPU_BASE_URL` defaults to `https://j1.pupuapi.com`;
- live mutation is disabled by default;
- credential and evidence paths default beneath `.local/`;
- no concrete token or phone number is present in defaults.

Run:

```bash
.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: RED because `pupu_assistant.config` does not exist.

**Step 3: Add the minimal package configuration**

Declare runtime dependencies:

```text
httpx
pydantic
pydantic-settings
typer
```

Declare development dependencies:

```text
pytest
pytest-asyncio
respx
ruff
```

Use a `src/` package and require Python `>=3.12`.

`Settings` must expose:

```text
pupu_base_url
pupu_timeout_seconds
pupu_verify_tls
pupu_credentials_path
pupu_evidence_path
pupu_allow_live_mutation
pupu_app_version
pupu_os_type
```

`.gitignore` must include:

```text
.venv/
.pytest_cache/
.ruff_cache/
__pycache__/
.env
.local/
.tools/
*.apk
*.xapk
*.apks
live-evidence*.json
```

**Step 4: Install and prove GREEN**

Run:

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/pupu_assistant/__init__.py src/pupu_assistant/config.py tests/test_config.py
git commit -m "Scaffold safe Pupu connector package"
```

## Task 2: Record the upstream audit with exact evidence

**Files:**

- Create: `docs/research/pupu-signature-audit-2026-07-21.md`
- Create: `docs/research/upstreams.json`
- Create: `scripts/audit_pupu_github.sh`
- Create: `tests/test_research_manifest.py`

**Step 1: Write the failing manifest test**

The test must require entries for:

```text
cddjr/check
YDEKQ/check
jo-dean/check
CHERWING/CHERWIN_SCRIPTS
fghwett/pupu
Churroser/PupuTool
```

Each entry must include repository URL, inspected SHA, inspected time, license conclusion, Pupu files, `seal` result, `sign` result, and cart result.

Run:

```bash
.venv/bin/python -m pytest tests/test_research_manifest.py -q
```

Expected: RED because the manifest is absent.

**Step 2: Add a reproducible read-only audit script**

The script must use `gh api`/`gh search code`, never clone into the project, and search:

```text
seal
sign
dac032e8fbb9900d840b960429b1a184
&*()*&
xxtea
cart
basket
购物车
```

It must also fetch `cddjr/check` issue #3 and list all Forks with their ahead/behind status.

**Step 3: Write the evidence document and manifest**

Record the current conclusion exactly:

- `cddjr/check` at `a7da0d90a55a0b345b70dde1549591a69e2cd417` has no `seal/sign` generator.
- Its issue #3 contains only a partial textual description.
- Both Forks are behind upstream and contain no forward implementation.
- Public GitHub code search found no complete implementation using the disclosed key or separator.
- Existing Pupu repositories cover sign-in/activity endpoints, not real cart control.
- The modified MD5 constants, modified Base64 alphabet, XXTEA key/input serialization, signed-header ordering, `seal` field serialization, and current protected-endpoint applicability remain unknown until client/traffic inspection.

Do not copy unlicensed upstream source into this repository.

**Step 4: Prove GREEN and rerun the audit**

Run:

```bash
bash scripts/audit_pupu_github.sh
.venv/bin/python -m pytest tests/test_research_manifest.py -q
```

Expected: script exits 0 and test passes.

**Step 5: Commit**

```bash
git add docs/research scripts/audit_pupu_github.sh tests/test_research_manifest.py
git commit -m "Document Pupu signature implementation audit"
```

## Task 3: Define the independent signature service

**Files:**

- Create: `src/pupu_assistant/integrations/__init__.py`
- Create: `src/pupu_assistant/integrations/pupu/__init__.py`
- Create: `src/pupu_assistant/integrations/pupu/models.py`
- Create: `src/pupu_assistant/integrations/pupu/signature.py`
- Create: `tests/integrations/pupu/test_signature.py`

**Step 1: Write failing signature contract tests**

The tests must require:

```python
class SignatureMode(StrEnum):
    NONE = "none"
    SEAL_SIGN = "seal_sign"

class PupuRequestContext(BaseModel):
    method: str
    path: str
    query: tuple[tuple[str, str], ...]
    body: bytes | None
    timestamp_ms: int
    device_id: str | None
    user_id: str | None
    su_id: str | None
    store_id: str | None
    place_id: str | None
    city_zip: str | None
    app_version: str
    os_type: str
    existing_headers: dict[str, str]

class SignedPupuRequest(BaseModel):
    path: str
    query: tuple[tuple[str, str], ...]
    body: bytes | None
    headers: dict[str, str]
    signature_mode: SignatureMode
    metadata: dict[str, str]

class PupuSignatureService(Protocol):
    def sign(self, request: PupuRequestContext) -> SignedPupuRequest: ...
```

Required behavior:

- request method is normalized to uppercase;
- headers are handled case-insensitively and emitted in one canonical spelling;
- public mode explicitly returns `SignatureMode.NONE`;
- protected mode without a verified algorithm raises `ProtectedSignatureUnavailable`;
- inputs and returned values are immutable from the caller's perspective;
- exception text never contains tokens, user IDs, device IDs, addresses, `sign`, or `seal`.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_signature.py -q
```

Expected: RED.

**Step 2: Implement only the proven modes**

Implement:

- `ExplicitNoSignatureService` for a route allowlist;
- `UnavailableProtectedSignatureService` that fails closed;
- `RoutingPupuSignatureService` selecting public versus protected routes.

Do not implement guessed MD5, Base64, XXTEA, or request-field ordering.

**Step 3: Prove GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_signature.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add src/pupu_assistant/integrations tests/integrations/pupu/test_signature.py
git commit -m "Add independent Pupu signature service contract"
```

## Task 4: Enforce the signed HTTP client call chain

**Files:**

- Create: `src/pupu_assistant/integrations/pupu/client.py`
- Create: `src/pupu_assistant/integrations/pupu/errors.py`
- Create: `tests/integrations/pupu/test_client.py`
- Create: `tests/architecture/test_pupu_http_boundary.py`

**Step 1: Write failing transport and architecture tests**

Transport tests must prove:

- the signature service is called exactly once before every request;
- only the returned normalized path, body, query, and headers reach `httpx`;
- the client never sends a protected request when signing fails;
- timeout, TLS, network, HTTP, JSON, and Pupu business errors are distinct typed exceptions;
- retries are limited to idempotent reads and connection-level failures;
- logs redact authorization, refresh token, user ID, device ID, address fields, `seal`, and `sign`.

The architecture test must scan `src/pupu_assistant/integrations/pupu/` and fail if `httpx`, `requests`, or `aiohttp` is imported outside `client.py`.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_client.py tests/architecture/test_pupu_http_boundary.py -q
```

Expected: RED.

**Step 2: Implement `PupuHttpClient`**

Expose one request method:

```python
async def request(
    self,
    method: str,
    path: str,
    *,
    query: Sequence[tuple[str, str]] = (),
    json_body: Mapping[str, object] | Sequence[object] | None = None,
    headers: Mapping[str, str] | None = None,
    signature_requirement: SignatureRequirement,
) -> PupuResponse:
    ...
```

The method builds `PupuRequestContext`, calls `signature_service.sign`, and only then calls `httpx.AsyncClient.request`.

**Step 3: Prove GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_client.py tests/architecture/test_pupu_http_boundary.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add src/pupu_assistant/integrations/pupu/client.py src/pupu_assistant/integrations/pupu/errors.py tests
git commit -m "Enforce signature-first Pupu HTTP transport"
```

## Task 5: Add the minimum real public-request validator

**Files:**

- Create: `src/pupu_assistant/integrations/pupu/system.py`
- Create: `src/pupu_assistant/validation/evidence.py`
- Create: `src/pupu_assistant/entrypoints/cli/main.py`
- Create: `scripts/validate_pupu_public.py`
- Create: `tests/integrations/pupu/test_system.py`
- Create: `tests/validation/test_evidence.py`

**Step 1: Write failing business-module and evidence tests**

Require `PupuSystemService.get_server_time()` to call `PupuHttpClient`, never a raw transport.

Evidence JSON must contain:

```text
endpoint
signature_mode
tested_at
http_status
pupu_errcode
request_result
response_shape
verified_in_mobile_app
failure_reason
```

Evidence must reject secret-bearing keys and values before writing.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_system.py tests/validation/test_evidence.py -q
```

Expected: RED.

**Step 2: Implement the public validator**

The script calls:

```text
GET /client/base/data
```

It must use the package client and explicit `signature_mode=none`. It may retry transient TLS handshake resets with bounded exponential backoff and must keep TLS certificate verification enabled.

**Step 3: Prove unit GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_system.py tests/validation/test_evidence.py -q
```

Expected: PASS.

**Step 4: Run the real endpoint**

Run:

```bash
.venv/bin/python scripts/validate_pupu_public.py
```

Expected live acceptance:

- HTTP response received from `j1.pupuapi.com`;
- Pupu `errcode` is `0`;
- response contains a plausible current server timestamp;
- `.local/evidence/public-server-time.json` records `signature_mode=none`.

If the endpoint fails after bounded retries, record the real failure; do not replace it with a mock result.

**Step 5: Commit**

```bash
git add src/pupu_assistant/validation src/pupu_assistant/entrypoints scripts/validate_pupu_public.py tests
git commit -m "Validate signature-first public Pupu requests"
```

## Task 6: Acquire and inspect a current official-client artifact

**Files:**

- Create: `scripts/fetch_pupu_android_artifact.py`
- Create: `scripts/inspect_pupu_artifact.sh`
- Create: `docs/research/pupu-android-6.4.5.md`
- Create: `tests/test_artifact_metadata.py`

**Step 1: Write the failing metadata test**

Require the research record to include:

```text
package_name
version_name
version_code
source_url
downloaded_at
sha256
signing_certificate_sha256
artifact_size
inspection_tools
```

The package name must be `com.pupumall.customer`. The artifact itself must remain ignored and uncommitted.

Run:

```bash
.venv/bin/python -m pytest tests/test_artifact_metadata.py -q
```

Expected: RED.

**Step 2: Fetch without trusting a search-result filename**

Prefer an official store or developer-controlled source. Verify:

- reported version is current;
- package name matches;
- signing certificate is recorded;
- SHA-256 is recorded;
- artifact is a valid APK/APKS/XAPK rather than HTML or a downloader wrapper.

If only a third-party source is available, mark provenance as untrusted and do not install it. Static inspection is allowed, but it cannot establish production authenticity.

**Step 3: Inspect statically**

Install analysis tools beneath `.tools/`, not system-wide. Search decompiled Java/Kotlin, native libraries, strings, assets, and Flutter/React Native bundles for:

```text
seal
sign
dac032e8fbb9900d840b960429b1a184
&*()*&
xxtea
pupuapi.com
/cart
/basket
购物车
pp-userid
pp-suid
```

Record exact class/function/native-library locations and the call chain. If logic is native or obfuscated, record that boundary instead of guessing.

**Step 4: Prove metadata GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_artifact_metadata.py -q
```

Expected: PASS.

**Step 5: Commit only scripts and evidence**

```bash
git add scripts/fetch_pupu_android_artifact.py scripts/inspect_pupu_artifact.sh docs/research/pupu-android-6.4.5.md tests/test_artifact_metadata.py
git commit -m "Inspect current Pupu Android signing path"
```

## Task 7: Import and sanitize a user-owned request trace

This task is required if static inspection does not fully reveal protected signing and cart endpoints.

**Files:**

- Create: `src/pupu_assistant/research/trace_import.py`
- Create: `src/pupu_assistant/research/trace_models.py`
- Create: `src/pupu_assistant/entrypoints/cli/trace.py`
- Create: `tests/research/test_trace_import.py`
- Create: `docs/guides/capture-pupu-traffic.md`

**Step 1: Write failing sanitizer tests**

Given HAR/mitmproxy JSON fixtures containing synthetic credentials and personal data, prove that persisted output removes:

```text
authorization
access_token
refresh_token
phone
name
address
longitude
latitude
device_id
user_id
seal
sign
cookie
```

Preserve only endpoint path, method, header names, body-key structure, value types, relative call order, response-key structure, and salted correlation hashes.

Run:

```bash
.venv/bin/python -m pytest tests/research/test_trace_import.py -q
```

Expected: RED.

**Step 2: Implement local-only trace import**

Raw trace inputs and derived secret-bearing intermediates must live beneath `.local/trace/`. The repository receives only the sanitizer and a synthetic fixture.

**Step 3: Document the capture path**

The guide must cover the least invasive options in this order:

1. user-owned Android emulator/device with a debugging proxy;
2. user-exported HAR from an already trusted debugging setup;
3. runtime instrumentation only if certificate pinning prevents option 1.

Do not ask the user to weaken the security of their primary phone. Never intercept traffic for any account other than the user's own.

**Step 4: Prove GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/research/test_trace_import.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/pupu_assistant/research src/pupu_assistant/entrypoints/cli/trace.py tests/research docs/guides/capture-pupu-traffic.md
git commit -m "Add safe Pupu request-trace research tooling"
```

## Task 8: Implement the verified `seal/sign` algorithm

Do not start this task until Task 6 or 7 yields at least two complete request vectors from the current client with known non-secret inputs and outputs.

**Files:**

- Modify: `src/pupu_assistant/integrations/pupu/signature.py`
- Create: `src/pupu_assistant/integrations/pupu/crypto.py`
- Create: `tests/fixtures/pupu/signature_vectors.redacted.json`
- Create: `tests/integrations/pupu/test_seal_sign.py`
- Modify: `docs/research/pupu-signature-audit-2026-07-21.md`

**Step 1: Write failing fixed-vector tests**

Vectors must cover:

- one protected GET;
- one protected POST;
- two different timestamps;
- deterministic injected random bytes;
- a single-field change that changes `sign`;
- the exact current Base64 alphabet and padding behavior;
- the exact current MD5 initialization/table modification;
- the exact XXTEA byte order, key derivation, plaintext serialization, and output encoding.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_seal_sign.py -q
```

Expected: RED.

**Step 2: Implement only evidence-backed behavior**

Add `SealSignPupuSignatureService`. Keep clock and random-byte generation injectable for vector tests. Return non-secret metadata:

```text
algorithm_revision
client_version
signed_header_names
timestamp_ms
```

Never log or persist generated `seal`, `sign`, raw account identifiers, or the complete signing preimage.

**Step 3: Prove vector GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_seal_sign.py tests/integrations/pupu/test_signature.py -q
```

Expected: PASS against current-client vectors.

**Step 4: Prove a protected read live**

Choose the least sensitive endpoint observed in the same client flow. Run it with the current account credentials and require Pupu authentication/signature success. Record only sanitized evidence.

If Pupu rejects the signature, return to vector analysis; do not proceed to cart mutation.

**Step 5: Commit**

```bash
git add src/pupu_assistant/integrations/pupu/signature.py src/pupu_assistant/integrations/pupu/crypto.py tests/fixtures/pupu/signature_vectors.redacted.json tests/integrations/pupu/test_seal_sign.py docs/research/pupu-signature-audit-2026-07-21.md
git commit -m "Implement verified Pupu seal sign service"
```

## Task 9: Add local credential onboarding and authenticated context

**Files:**

- Create: `src/pupu_assistant/integrations/pupu/credentials.py`
- Create: `src/pupu_assistant/integrations/pupu/auth.py`
- Create: `src/pupu_assistant/integrations/pupu/context.py`
- Create: `src/pupu_assistant/entrypoints/cli/auth.py`
- Create: `tests/integrations/pupu/test_credentials.py`
- Create: `tests/integrations/pupu/test_auth.py`

**Step 1: Write failing credential tests**

Require:

- local credential file mode `0600`;
- atomic replace when refresh token rotates;
- secrets excluded from `repr`, logs, exceptions, evidence, and CLI output;
- missing credentials produce `AuthenticationRequired`;
- authenticated context includes the exact device/user/store fields required by current-client evidence.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_credentials.py tests/integrations/pupu/test_auth.py -q
```

Expected: RED.

**Step 2: Implement import-first onboarding**

Support local interactive import of `device_id` plus `refresh_token`/current bearer material without command-line arguments or shell history exposure.

If imported credentials are unavailable or rejected, implement the currently observed phone/SMS flow behind the same auth service. The CLI prompts for the user's phone number locally and pauses for the SMS code; it must never persist the phone number after login unless the user explicitly opts in.

**Step 3: Prove unit GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_credentials.py tests/integrations/pupu/test_auth.py -q
```

Expected: PASS.

**Step 4: Prove real authentication**

Run the CLI and require a successful authenticated read such as current user or current store. Record sanitized evidence.

**Step 5: Commit**

```bash
git add src/pupu_assistant/integrations/pupu/credentials.py src/pupu_assistant/integrations/pupu/auth.py src/pupu_assistant/integrations/pupu/context.py src/pupu_assistant/entrypoints/cli/auth.py tests/integrations/pupu
git commit -m "Add local Pupu credential onboarding"
```

## Task 10: Implement current store, product search, and cart reads

**Files:**

- Create: `src/pupu_assistant/integrations/pupu/stores.py`
- Create: `src/pupu_assistant/integrations/pupu/products.py`
- Create: `src/pupu_assistant/integrations/pupu/cart.py`
- Create: `tests/integrations/pupu/test_stores.py`
- Create: `tests/integrations/pupu/test_products.py`
- Create: `tests/integrations/pupu/test_cart.py`

**Step 1: Write failing business-module tests**

Use the exact current-client endpoint paths and payload shapes discovered in Tasks 6/7. Tests must prove:

- current store and place context are resolved before catalog/cart calls;
- search returns platform product ID, SKU/spec ID if distinct, name, current price, unit/specification, stock state, store ID, and capture time;
- cart read returns platform product identity and absolute quantity;
- unknown response fields are tolerated and schema drift is reported;
- all three modules depend only on `PupuHttpClient`.

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_stores.py tests/integrations/pupu/test_products.py tests/integrations/pupu/test_cart.py -q
```

Expected: RED.

**Step 2: Implement the minimal read path**

Do not port the direct order-creation logic from `cddjr/check`. Reuse only evidence-backed header/context knowledge, retaining attribution where source code is copied under MIT.

**Step 3: Prove unit GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/integrations/pupu/test_stores.py tests/integrations/pupu/test_products.py tests/integrations/pupu/test_cart.py -q
```

Expected: PASS.

**Step 4: Prove all reads live**

With the user's account:

- resolve the active delivery store;
- search a harmless item requested by the user or a low-cost staple;
- read the current real cart;
- save sanitized evidence for each interface.

**Step 5: Commit**

```bash
git add src/pupu_assistant/integrations/pupu/stores.py src/pupu_assistant/integrations/pupu/products.py src/pupu_assistant/integrations/pupu/cart.py tests/integrations/pupu
git commit -m "Add live Pupu store product and cart reads"
```

## Task 11: Implement two-phase real cart mutation

**Files:**

- Create: `src/pupu_assistant/domain/cart_write.py`
- Create: `src/pupu_assistant/application/cart_control.py`
- Create: `src/pupu_assistant/storage/confirmation_store.py`
- Create: `src/pupu_assistant/entrypoints/cli/cart.py`
- Create: `tests/domain/test_cart_write.py`
- Create: `tests/application/test_cart_control.py`
- Create: `tests/storage/test_confirmation_store.py`

**Step 1: Write failing safety tests**

Require:

- preview includes product ID, name, before quantity, target quantity, unit price, estimated delta, store, and expiry;
- `confirmation_id` is bound to the preview hash and expires;
- changing product, quantity, price, stock, store, or current cart invalidates confirmation;
- confirmation is one-time use;
- live mutation requires both `PUPU_ALLOW_LIVE_MUTATION=true` and the exact confirmation phrase;
- mutation request uses an idempotency key if the current client/API supports one;
- a timeout after write is treated as unknown until cart read resolves it;
- success is impossible until read-back matches the expected absolute quantity;
- partial/unexpected state is reported without retrying a non-idempotent mutation blindly.

Run:

```bash
.venv/bin/python -m pytest tests/domain/test_cart_write.py tests/application/test_cart_control.py tests/storage/test_confirmation_store.py -q
```

Expected: RED.

**Step 2: Implement preview**

CLI example:

```bash
.venv/bin/pupu cart preview --product-id PRODUCT_ID --quantity 1
```

The preview writes a short-lived local confirmation record beneath `.local/`, not to Git.

**Step 3: Implement confirmed execution and verification**

CLI example:

```bash
.venv/bin/pupu cart execute CONFIRMATION_ID
```

The command must:

1. request the exact confirmation phrase interactively;
2. re-read store, product, stock, price, and cart;
3. invalidate on any material change;
4. call the observed cart mutation endpoint through `PupuHttpClient`;
5. re-read cart;
6. compare product identity and absolute quantity;
7. record sanitized evidence.

**Step 4: Prove unit GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/domain/test_cart_write.py tests/application/test_cart_control.py tests/storage/test_confirmation_store.py -q
```

Expected: PASS.

**Step 5: Perform the real one-item acceptance**

Use an item and quantity explicitly visible in the preview. Do not choose an expensive item and do not add more than one unit unless the user instructs otherwise.

Acceptance requires:

- preview shown to the user;
- user confirms the exact preview;
- Pupu mutation response succeeds;
- immediate cart read contains the expected product and quantity;
- user verifies that the same item appears in the phone app.

If adding the item would unexpectedly replace or clear an existing cart, stop before mutation and report the discovered semantics.

**Step 6: Commit**

```bash
git add src/pupu_assistant/domain src/pupu_assistant/application src/pupu_assistant/storage src/pupu_assistant/entrypoints/cli/cart.py tests
git commit -m "Add confirmed and verified Pupu cart control"
```

## Task 12: Final verification, report, review, and GitHub sync

**Files:**

- Create: `docs/validation/pupu-live-validation-2026-07-21.md`
- Create: `README.md`
- Modify: `.env.example`

**Step 1: Write the validation report**

List every inspected or exercised interface in a table with:

```text
capability
endpoint path
signature mode
unit/contract status
real-request status
tested at
account scope
mobile-app verified
evidence file
failure reason
```

Explicitly separate:

- verified by real request;
- verified only against current-client vectors;
- unit-tested only;
- not implemented;
- blocked.

**Step 2: Run the complete automated suite**

Run:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

Expected: all checks pass.

**Step 3: Run the real validators again**

At minimum rerun:

```text
server time
authenticated identity/store
product search
cart read
cart add
post-add cart read
```

Do not rerun a non-idempotent cart addition without a fresh preview and explicit confirmation.

**Step 4: Inspect the secret boundary**

Run:

```bash
git status --short
git diff --check
git grep -n -I -E 'Bearer |refresh_token|access_token|authorization|phone|device_id|pp-userid|pp-suid|\"seal\"|\"sign\"' -- ':!docs/research/*' ':!tests/fixtures/*'
```

Expected: no real credential or personal value is tracked.

**Step 5: Request code review**

Use `superpowers:requesting-code-review`, fix every correctness or safety issue through TDD, then rerun the complete suite and live read checks.

**Step 6: Commit and push**

```bash
git add README.md .env.example docs/validation
git commit -m "Document real Pupu cart validation"
git push origin main
```

Final handoff must state the exact Git SHA and must not claim real cart control unless the Task 11 live acceptance evidence exists.
