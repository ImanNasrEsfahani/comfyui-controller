# Phase 03 — CHANGELOG / source pin

Source GitHub branch `main` at implementation: `2738df39a17b5f93c61ada6b955a56d121dc7101` (commit `Phase 02 - Development`). GitHub accessed strictly READ-ONLY.

## New modules
- `backend/app/owner_repository.py`: user SQL predicates for jobs, count/history/search/cursor, input/output assets, immutable verified ownership, cancel and terminal hide. Unverified/orphan resources deny by default.
- `backend/app/owner_api.py`: optional same-path cookie-only owner router; cross-user reads yield 404. Private upload with media probing, short-lived R2 ticket after owner+CSRF, stream-only output download, reference ownership checks; Session never implies Admin/Worker permission.
- `frontend/src/ownerClient.js`: isolated future Auth UI adapter, same-origin cookies, CSRF, in-memory identity, clear legacy cache and stale responses after account change. NOT wired into existing `App.jsx` in this phase.
- `scripts/phase03_prepare_checkout.py`: source-pinned, fail-closed generator for existing `backend/app/main.py` and `backend/app/job_records.py`, on a complete exact checkout; default dry-run.
- `backend/owner.env.example`: feature flag initially false.
- `tests/test_phase03_owner.py`, `tests/test_phase03_patch.py`, `tests/test_phase03_owner_client.mjs`: synthetic A/B HTTP, SQLite, patch, client tests.

## Source-pinned generated edits (requires local full checkout)
- `main.py`: imports Phase02 router (missing from live base `main.py`) and Phase03 router. When `OWNER_ISOLATION_ENABLED=true`, owner routes register *before* legacy routes. Otherwise existing API behavior is unchanged.
- `job_records.py`: Worker-saved job assets inherit the persisted parent Job owner and verified state when Phase01 schema exists, ignoring forgeable worker owner fields; legacy schemas retain their original path. This is a code-only change, **not** permission to trust unreviewed results.

## Intentionally NOT implemented (closed rather than insecure)
- Authenticated `POST /api/jobs` and `POST /api/jobs/{id}/retry` return 503 for owner sessions. The existing `db.create_job` + global `client_request_id` index and legacy remote retry cannot atomically establish verified ownership before Worker claim; exposing them would create BOLA/race risk.
- Full owner-scoped dedup/input usage persistence/lineage, Grants/Projects, user-safe Workflow publish flows and complete front-end integration require further work.
- Old admin GPU controls still depend on private `APP_INTERNAL_TOKEN`, never a user cookie. Multi-tenant admin content policy has **not** been proven.

No GitHub changes, production migrations, real R2/GPU changes, or file deletion were performed.
