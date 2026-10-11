# Phase11 handoff

**Status: PARTIAL / BLOCKED**, not DONE_VERIFIED. Read-only base `main` `41b11228bc4728b2781966eafb6d23fe1831cb2f` (to be rechecked before packaging). Delivered opt-in signed Worker envelope, R2 owner/slot input bindings, warm cache integrity checks, bytes-based output validation, independent fenced receipt journal, observed hello API, local migration-copy and SHA-guarded installer. No direct GitHub or provider changes.

The **new Claim endpoint intentionally returns 503**. Existing legacy Worker pipeline, which uses direct_queue.claim -> /prompt and HEAD-only storage.validate_outputs, is NOT replaced by these modules when flags are OFF. Rebuild only on exact Git SHA; do not run Phase10 installer against newer base.

Must resolve before activation: audited approved GLOBAL-RULES/DECISIONS; Phase03 owner-safe idempotent Job + Retry; Phase07 worker image signing/scanning + verified compatibility; Stage09/10 real ComfyUI graph compilation with stage-specific model/LoRA, typed edges and tested node classes; provenance-backed v11 signing issuer; secure allocator that picks only eligible model/profile and binds claim atomically to Job lease; trusted worker manifest and checksum rotation; real multi-input R2 staging, ComfyUI output-to-R2 with decoded verification integrated in the actual finalizing callback, and Gallery output record linkage; lease/interrupt recovery during network partitions; deploy/rollback rehearsal and cost-approved GPU E2E for at least one image tool. Video postponed until Phase13.

Current output bytes validation is bounded to 250 MiB in memory per object, video requires an external trusted probe, and cache reuse is warm-container only. These are staging prototypes, not guarantees for high-throughput/multi-GB video.
