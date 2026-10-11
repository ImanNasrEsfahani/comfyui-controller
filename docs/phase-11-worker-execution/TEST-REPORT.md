# TEST REPORT — Phase11

**Baseline GitHub main:** `41b11228bc4728b2781966eafb6d23fe1831cb2f`. Python 3.13, pytest in offline isolated container; SQLite in-memory and SQLite backup copy; R2 fake object client; Pillow decoded 8×12 PNG; no GPU/network.

```bash
cd <unpacked_zip_or_repo>
python -m pytest -q tests/test_phase11_*.py
```

**PASS: 52/52 dedicated isolated Python tests** at last recorded run, including HMAC, lease expiry, input URL/mime injection, wrong image/model/LoRA, slot authorization A/B, R2 integrity and partial output, warm cache reuse, bad checksum, symlink rejection, media byte validation, duplicate and stale result, cancellation state, migration idempotence and source preservation, service token vs browser cookie, and SHA-guarded local source patch primitives. One third-party TestClient per-request cookie deprecation warning (non-failure).

**Limited prior-stage regression**: 13/13 Phase10 node-graph JavaScript tests passed when unpacking prior delivered ZIP. A broader `node --test tests/test_phase10_*.mjs` on the incomplete prior ZIP produced 13 PASS + 1 module-load FAIL because `frontend/src/auth/api.js` was absent from that ZIP fixture; this is an **incomplete environment**, NOT a verified full regression.

**NOT RUN**: `npm run build`, Playwright / 360px / RTL, full current-repository pytest, actual v11 composite installer on exact complete Git checkout, actual Worker Docker build/scan/signature, real R2 presigned requests, Salad deploy, cold image pull, runtime attestation, real ComfyUI inference / seed / LoRA graph fidelity, real interrupted/cancelled processing, staging Rollback and Phase03 owner-safe accepted jobs.

Acceptance mapping:

- **AT-11-01 PARTIAL**: cryptographic signed envelope, compatibility inputs and invalid image/model/graph rejected offline; actual signed claim generator and GPU inventory remain blocked.
- **AT-11-02 PARTIAL**: simulated lease expiration, stale active pointer, duplicate completion, cancel_requested guard and partial output rejection PASS in independent receipt journal, but not proven wired through real current queue.
- **AT-11-03 NOT RUN**: no cost-approved GPU, no model/profile inference test.
- **AT-11-04 NOT RUN**: actual ComfyUI interrupt unavailable; mocked journal only.

Do not upgrade this report to DONE_VERIFIED without complete staging E2E and user approval of architecture/security decisions.
