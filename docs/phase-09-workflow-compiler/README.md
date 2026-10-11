# Phase 09 — Safe Versioned Workflow Compiler (offline/staging candidate)

**Source main SHA:** `3d7e2539cec80f7087188101fd30b38f161011ec` (2026-10-11, read-only). **Status:** `PARTIAL / BLOCKED`, **not** `DONE_VERIFIED`.

## What exists

- Owner-isolated Workflow definitions and draft/validated/published immutable revisions; SQLite revision `009_versioned_safe_workflows` is explicit and additive.
- Strict allowlisted **semantic** node types; exact named typed ports, edge compatibility, duplicate connections, DAG cycle checks, missing required inputs, output type checks, graph size caps, canonical JSON and SHA256.
- Per-version compile-preview under owner session and CSRF; opaque Asset ID verification, uint64 seeds sent as strings, private immutable per-owner request hashes, 409 for changed request with same idempotency key.
- Only scrubbed preview metadata is returned by API. User prompt, original graph, private Asset IDs and storage keys are not included in list/preview responses. Original private input data can be present in owner-only SQLite snapshot records, so backup/log policy applies.
- Five structurally valid offline graph templates: `text2img`, `img2img`, `multi_ref`, `image2video`, `text2video`. The advanced canvas editor is a Phase10 item. User UI is a wizard-like template selector plus version list and compile preview.
- Separate `/api/v2/semantic-*` paths avoid changing legacy `/api/workflows`, existing `JobIn v1`, Worker APIs, or any Salad image/group.

## Not present / intentionally gated

**Compiled graph is not a verified executable ComfyUI payload**: `CheckpointLoaderSimple` requires an approved runtime checkpoint binding, video/multi-reference node types are semantic placeholders, no per-node Worker inventory attestation exists. `runtime_verified=false`, `dispatch_allowed=false` always. No new queue, Job, Retry, GPU call or R2 operation.

`WORKFLOW_COMPILER_ENABLED=false` by default; `WORKFLOW_PUBLISH_METADATA_ENABLED=false` by default. Even metadata-only publish requires Superadmin + user confirmation + recorded Phase07 tested-pass active compatibility. Actual worker deployment remains prohibited. Phase08 parameter schema resolution, verified LoRA mapping, real Job immutable retry/persistence and worker semantic snapshot parity are follow-on integrations, not asserted complete.

`GLOBAL-RULES.txt`, approved `DECISIONS.md` and owner migration sign-off were not supplied. They remain release blockers. See RELEASE-GATE.md and HANDOFF.md.
