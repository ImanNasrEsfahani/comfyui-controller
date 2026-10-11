# Phase 06 — Private gallery, multiple references, full-screen media

Source of truth: GitHub read-only `main` at `f2932e390705631b899c47fc4d06567b09fd1bfc` (`phase 05 - development`). The base SHA was checked before development and rechecked before packaging. All changes below are **LOCAL PROPOSALS**, not deployed.

**Release status: PARTIAL / BLOCKED.** Phase03 atomic owner-safe Generate/Retry and Phase05 verified staging are not complete. `GLOBAL-RULES.txt`, `DECISIONS.md`, approved `LEGACY_OWNER_PLAN`, real restored DB and actual R2 credentials/permissions were not supplied. Sharing remains disabled; absent deletion/retention decisions are not guessed.

## Scope and status

| Requirement | Result | Notes |
|---|---|---|
| Private `/library` | Implemented and synthetic HTTP tested | SQL `owner_user_id`, signed owner+filter-bound cursor, file-type filter, scoped soft-delete; model/project filters return 422 explicitly until indexed schema exists |
| Asset details | Implemented | Safe metadata, input reference history where available, no raw storage keys |
| Separate thumbnails | Partial | Uploads create a separate private WebP thumbnail; previously stored outputs without variants do NOT fetch full originals for grid. Output thumbnail backfill needed |
| Full-screen | Implemented UI, browser NOT RUN | Keyboard focus, Esc, arrows, wheel/zoom/fit/actual-size, touch swipe, video controls and local comparison; no validated Playwright on actual browser |
| Upload with reference cards | Partial | Single-file safe authenticated uploads per card, multiple cards and role/order/edit/remove, abort/retry UI; progress stays **unknown** (fetch offers no upload byte progress). Workflow contract-driven roles and resumed multipart unsupported |
| Reuse output | Draft-only, tested | POST `/api/assets/:id/reuse` authenticates owner and returns a draft binding; no dispatch, job source lineage write or producer job auto-creation |
| Immutable reference schema | Implemented but not wired to Generate | Opt-in `job_input_assets` table with transactional owner triggers, no mutable references; writing by live Job creation remains BLOCKED |
| Download original | Synthetic HTTP PASS | Controller-authenticated proxy; no persistent signed URL exposed to UI; optional short-lived 60-second presign ticket can be issued after CSRF/owner check |
| Soft-delete | Synthetic HTTP PASS | `asset_deletions` tombstone and SQL exclusion across new and Phase03 owner endpoints; referenced assets return 409; R2 bytes and source jobs never physically deleted |
| Admin/content isolation | Existing Phase03/05 policy preserved | New routes use user session only; no old admin token, worker token, public bucket or secret/prompt in gallery indexes |

## Open gaps

- Phase03 Generate/Retry/immutable source-lineage cannot be claimed complete and are explicitly disabled.
- Legacy R2 object-key owner mapping, consistency, thumbnails, storage ACLs, real signed URL expiry, S3 `HEAD`/transport and worker late-result callbacks require staging with a verified copied DB and real R2.
- Provider output thumbnail and video poster generation, old media variant backfill and rich model/project filters are not delivered.
- Asset retention/grace, deletion execution policy, security/AV scanning requirements, EXIF export policy require decisions. The new private thumbnail strips EXIF by re-encoding; original file is preserved unchanged.
- Full Vite build, React/Playwright 360px RTL & keyboard, complete repository Python/Worker regressions and two-user Generate->Reuse E2E were not executed on this environment (the checkout is unavailable to the container, due to blocked DNS).

See `API-CONTRACT.md`, `DEPLOY-ROLLBACK.md`, `TEST-REPORT.md`, `HANDOFF.md`.
