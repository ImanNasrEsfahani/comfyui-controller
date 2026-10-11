# Phase 11 — Worker execution and runtime integrity (staging proposal)

Base read-only GitHub `main`: `41b11228bc4728b2781966eafb6d23fe1831cb2f` (11 October 2026 UTC). Never push, commit, migrate production, start Salad or consume GPU hours from this package.

**Overall release status: PARTIAL / BLOCKED, not DONE_VERIFIED.** The deliverable is an additive, opt-in security foundation with real executable Python modules and local tests, not an end-to-end validated multi-model Worker. Phase09/10 and Phase03 owner-safe Job creation are not DONE_VERIFIED, Phase07 real image/model compatibility and trusted OCI evidence are not verified. User-provided `GLOBAL-RULES.txt`, approved `DECISIONS.md`, actual staging GPU approval/credentials and official model pair list are absent.

What is implemented locally:

- HMAC-SHA256 lease- and attempt-bound signed envelope (`backend/app/worker_v11_contract.py` and byte-identical `salad-worker/v11_contract.py`). Pins OCI digest, model/workflow/deployment versions, compiled graph SHA256, expected input asset hashes, LoRA IDs/weights and output attempt prefix; rejects unsigned, stale, wrong-image, unknown node, unverified model/LoRA claims.
- Owner-bounded input authorization (`worker_v11_owner.py`), checking verified job/asset ownership, immutable `job_input_assets` slot/role, soft-deletion and actual R2 content hash. A Worker cannot select a different Asset by guessing an ID.
- Worker input staging (`v11_execution.py`) into restricted ComfyUI input directory, verifies full bytes and substitutes only typed `asset_slot` placeholders; cleans temporary input files. Opt-in bootstrap refuses operation without checksum-pinned local runtime manifest and service-only secrets.
- Warm-container artifact cache (`v11_cache.py`) using SHA256 + exact byte size, atomic promotion and HTTPS trusted origin; rejects redirects, symlink roots, corrupt/partial files. **No guarantee across scale-to-zero**.
- Strict R2 media validation (`worker_v11_media.py`) reads real data, checks image decoder, magic bytes, pixel bounds, claimed MIME/size, attempt prefix. Video requires a trusted decoding/probe callback; no video model runtime claim. Per-object partial status survives verification failures.
- Additive Phase11 observations/receipt migration, append-only observation triggers, attempt-fenced progress, cancelled-vs-cancel_requested distinction and exact result receipt (`worker_v11_state.py`). Functions check the underlying controller Job lease and current attempt on every call. No direct migration of existing historical output rows.
- Service-only optional `POST /api/v2/worker/hello` shows **unverified** compatibility, never a green model Ready. `POST /api/v2/worker/claim` deliberately returns 503 until a trusted scheduler can issue signed claims. All new flags default OFF.

**Missing integration gates**: Phase09's compiled graph is still structurally simulated rather than attested as a ComfyUI API graph on an approved node inventory; no atomic Phase03 Job acceptance; no controller signature issuer attached to an authenticated enqueue/claim; no demonstrated server-side verified worker artifact provenance; no safe multi-model allocator; no fully integrated v11 result validation into the legacy `/api/worker/complete` route or the Gallery; no real Cold Start/ComfyUI/R2 lifecycle smoke; no real cancel interrupt. Module correctness is NOT proof of a working GPU pipeline. Legacy routes are retained and unchanged when flags are OFF.

See `API-CONTRACT.md`, `TEST-REPORT.md`, `RELEASE-GATE.md`, `DEPLOY-ROLLBACK.md` and `HANDOFF.md`.
