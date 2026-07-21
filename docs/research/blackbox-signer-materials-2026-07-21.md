# Black-box Pupu signer materials - 2026-07-21

This note documents the offline signer materials added after the static `seal/sign` follow-up.

## Files committed

- `.local/bin/pupusgn` - Mac/Linux runnable Python entrypoint. It reads JSON from stdin or `--input`, writes JSON to stdout, and does not send HTTP requests.
- `.local/pupusgn-test.json` - redacted supplied-result signer fixture with two runnable cases:
  - `protected_read_product_detail_popup`
  - `business_write_cart_purchasing_product`
- `.local/pupusgn-sdu-input.json` - redacted stdin-to-local-sdu fixture with no precomputed signatures:
  - `sdu_product_detail_popup`
  - `sdu_cart_purchasing_product`
- `.local/pupusgn-signature-cache.example.json` - redacted exact-match cache format for real headers captured from an authorized local client.
- `.local/pupu-cases.json` - redacted route catalog for product reads, cart reads, and cart add/update candidates.
- `src/pupu_assistant/integrations/pupu/blackbox_signer.py` - parser, validator, supplied-result merger, optional local provider-command adapter, and exact-match signature cache lookup.
- `tests/integrations/pupu/test_blackbox_signer.py` - fail-closed, merge, CLI, and fixture redaction tests.

`.gitignore` now keeps generic `.local/*` ignored, but explicitly allows only the committed signer/material files above. Local evidence, private runtime inputs, credentials, APKs, and hook captures remain ignored.

## Contract

Minimal input shape:

```json
{
  "request": {
    "method": "GET",
    "path": "/client/product/storeproduct/detail_popup/<STORE_ID>/<STORE_PRODUCT_ID>",
    "query": [["zip", "<CITY_ZIP>"]],
    "headers": {
      "pp-version": "6.4.9",
      "pp-os": "20",
      "pp-deviceid": "<PP_DEVICE_ID>",
      "pp-time": "<TIMESTAMP_MS>"
    }
  },
  "blackbox_result": {
    "signed_headers": {
      "pp-time": "<TIMESTAMP_MS>",
      "pp-seqid": "<SEQ_ID_FROM_BLACKBOX>",
      "seal": "<SEAL_FROM_BLACKBOX>",
      "sign-v3": "<SIGN_V3_FROM_BLACKBOX>"
    }
  }
}
```

Output shape:

```json
{
  "ok": true,
  "network_performed": false,
  "signature_mode": "seal_sign",
  "method": "GET",
  "path": "/client/...",
  "query": [["zip", "<CITY_ZIP>"]],
  "headers": {
    "pp-version": "6.4.9",
    "seal": "<SEAL_FROM_BLACKBOX>",
    "sign-v3": "<SIGN_V3_FROM_BLACKBOX>"
  },
  "metadata": {"source": "supplied_blackbox_result"}
}
```

If no `blackbox_result` or local provider command is available, the tool exits with code `2` and returns:

```json
{"ok": false, "network_performed": false, "error": "blackbox_signature_unavailable"}
```

## Mac usage

```bash
chmod +x .local/bin/pupusgn
.local/bin/pupusgn --input .local/pupusgn-test.json --case protected_read_product_detail_popup --pretty
.local/bin/pupusgn --input .local/pupusgn-test.json --case business_write_cart_purchasing_product --pretty
```

Private runtime input files should stay outside Git, for example `.local/private/runtime-sign-input.json`.

Optional local provider command mode:

```bash
PUPUSGN_BLACKBOX_CMD="/absolute/path/to/private-signer" \
  .local/bin/pupusgn --input .local/private/runtime-sign-input.json --pretty
```

Preferred local sdu/signer command mode for full stdin request signing:

```bash
PUPUSGN_SDU_CMD="/absolute/path/to/private-sdu" \
  .local/bin/pupusgn --input .local/pupusgn-sdu-input.json --case sdu_product_detail_popup --pretty

.local/bin/pupusgn \
  --input .local/pupusgn-sdu-input.json \
  --case sdu_cart_purchasing_product \
  --sdu-command "/absolute/path/to/private-sdu" \
  --pretty
```

In sdu mode the wrapper sends this stdin shape to the private command:

```json
{
  "schema_version": 1,
  "request": {
    "method": "POST",
    "path": "/client/...",
    "query": [["store_id", "<STORE_ID>"]],
    "body": {"items": [{"store_product_id": "<STORE_PRODUCT_ID>"}]},
    "body_sha256": "<computed-by-wrapper>",
    "headers": {"pp-deviceid": "<PP_DEVICE_ID>"},
    "context": {"pp_device_id": "<PP_DEVICE_ID>", "user_id": "<USER_ID>"}
  }
}
```

The private command must return JSON containing `signed_headers` or `headers` with at least one `seal`/`sign` header. The wrapper itself still performs no network I/O; it only calls the local command and validates that the returned JSON contains at least one `seal`/`sign` header.

## Exact-match signature cache mode

This is the implemented fallback when no reusable local SDK/sdu exists but real signed headers have been captured for an exact request. It does not invent or recompute `seal/sign`; it only reuses a previously captured header set when the current request fingerprint matches exactly.

Fingerprint properties:

- includes method, path, query, normalized non-signature headers, context, and body SHA-256;
- does not store raw body content;
- ignores existing `seal/sign` artifacts in input headers;
- fails closed on miss or expired entry.

Usage:

```bash
PUPUSGN_SIGNATURE_CACHE="/absolute/path/to/private-signature-cache.json" \
  .local/bin/pupusgn --input .local/pupusgn-sdu-input.json --case sdu_product_detail_popup --pretty

.local/bin/pupusgn \
  --input .local/pupusgn-sdu-input.json \
  --case sdu_cart_purchasing_product \
  --signature-cache "/absolute/path/to/private-signature-cache.json" \
  --pretty
```

Cache entry shape:

```json
{
  "request_fingerprint": "sha256:<computed-by-request_fingerprint>",
  "expires_at": "2026-07-22T12:00:00Z",
  "signed_headers": {
    "seal-v3": "<REAL_CAPTURED_SEAL_V3>",
    "sign-v3": "<REAL_CAPTURED_SIGN_V3>",
    "pp-seqid": "<REAL_CAPTURED_SEQID>",
    "pp-time": "<TIMESTAMP_MS>"
  },
  "metadata": {"source": "authorized_local_app_capture"}
}
```

The Frida helper added on 2026-07-22 writes this private cache directly:

```bash
python scripts/capture_pupu_signatures.py
```

See `docs/research/pupu-frida-hook-capture-2026-07-22.md`.

## Route notes from 6.4.9 Hermes

Static Hermes references used for the committed case catalog:

- Protected product read candidates:
  - `GET /client/product/storeproduct/unit_price/detail/{id}` (`withSecSign` observed)
  - `GET /client/product/storeproduct/detail_popup/...` (`withSecSign` observed)
- Shopping-cart read/write candidates:
  - `GET /client/shopping_cart/shopping_cart/bff/recommend_info`
  - `GET /client/shopping_cart/shopping_cart/init_piecing_page_desc`
  - `POST /client/shopping_cart/shopping_cart_item/bff/purchasing_product`
  - `POST /client/shopping_cart/shopping_cart_item/bff/purchasing_product/batch`
  - `PUT /client/shopping_cart/shopping_cart_item/bff/selection_status`
  - `PUT /client/shopping_cart/shopping_cart_item/bff/selection_status_all`

The cart write cases are fixture-only until a real account owner supplies current signed headers and the normal preview/confirmation/readback state machine is connected.

## Credential handling

Committed fixtures use placeholders only:

- `<PP_DEVICE_ID>`
- `<USER_ID>`
- `<SUID>`
- `<STORE_ID>`
- `<PLACE_ID>`
- `<CITY_ZIP>`
- `<BLACKBOX_...>`

Do not commit private runtime files, hook captures, device identifiers, account identifiers, or one-time challenge material.
