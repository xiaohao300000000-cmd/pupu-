# Pupu seal/sign alternatives - 2026-07-22

This note records the follow-up after the question: if no reusable `sdu`/private signer is present, is there another way to produce usable `seal/sign` material?

## Current conclusion

There are three technically distinct paths:

1. **Reusable local signer / SDK bridge** - best path when an authorized local signer exists. `.local/bin/pupusgn --sdu-command` already supports this and passes full method/path/query/body/headers/context via stdin.
2. **Exact-match real signature cache** - implemented in this follow-up. If real signed headers are captured from an authorized local client for the exact request, `.local/bin/pupusgn --signature-cache` can return those real headers without storing credentials or raw bodies in Git.
3. **APK/static recovery or runtime dump** - still research-only. The available 6.4.9 APK is SecNeo protected; the visible Java layer is a wrapper around `libDexHelper.so`, and the real app classes remain in packed payload data.

No code path has been changed to fake, downgrade, or synthesize `seal/sign`. Protected requests still fail closed unless a supplied result, a local signer command, or an exact cache hit provides signed headers.

## Static APK probe

Artifact inspected locally:

- `C:\Users\10579\work\pupu-audit\artifacts\extract649\classes.dex`
- SHA-256: `7c02c99e50ff647e411570275a38f20f47e0e5d6adb5b8b65f2cc341110b7489`
- size: `53608828`

Key offsets observed:

- real DEX structured area appears to end around `0x915c`;
- `dexdata0` marker at `0x9168`;
- appended payload footer ends with `fdex` at `0x3320178`;
- footer contains little-endian pointer `0x915c`;
- `HEADER_SEAL` strings at `0x223d124`, `0x223d131`, `0x223d141`;
- `HEADER_SIGN` strings at `0x223d151`, `0x223d15e`, `0x223d16f`, `0x223d17f`;
- ZIP local-header marker `PK\x03\x04` at `0x4355e8`;
- Hermes-like magic `c6 1f bc 03` at `0x2ee7b07`.

Interpretation: this is consistent with a protected SecNeo-style payload where the visible DEX is only the loader and real classes are appended/loaded by `libDexHelper.so`. Static recovery is not a missing single Python step; it requires either successful unpacking of that payload format or a runtime memory dump after the loader materializes the app classes.

## Implemented fallback: exact-match signature cache

New support:

- `request_fingerprint(request)` computes a secret-free exact-match hash:
  - method/path/query;
  - normalized non-signature headers;
  - context fields;
  - body SHA-256 instead of raw body.
- `sign_with_signature_cache(request, cache_path)` reads a private cache:
  - returns signed headers only if the fingerprint matches;
  - rejects expired entries;
  - returns `network_performed=false`;
  - fails closed on miss.
- `.local/bin/pupusgn --signature-cache <path>` and `PUPUSGN_SIGNATURE_CACHE` expose this through the stdin CLI.
- `.local/pupusgn-signature-cache.example.json` documents the committed placeholder-only format.

This gives a usable "another way" for real headers: capture once from an authorized local app/client, store only the request fingerprint plus real signed headers in a private ignored cache, then replay only exact matching requests while the captured header set is still valid.

## Verification commands

Fresh checks for this follow-up:

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check src tests
git diff --check
```

