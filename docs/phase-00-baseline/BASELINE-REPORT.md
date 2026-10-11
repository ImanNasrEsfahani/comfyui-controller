# PHASE 00 — Baseline Report

- **Date (report authored):** 2026-10-10 (user-local date)
- **Repository:** https://github.com/ImanNasrEsfahani/comfyui-controller
- **Branch / observed HEAD:** `main` / `bea004d97a264f892cfae6dec9c4f691aed40a39`
- **Commit timestamp:** 2026-10-05T00:00:49Z (`fix problem 1-6 2`)
- **Source:** read-only authenticated GitHub connector: repository metadata, branch, recursive Git tree and selected files PINNED by SHA.
- **Scope:** Phase 00 discovery / architecture decision records / OFFLINE read-only tools only. GitHub never modified; no production or provider access attempted.
- **Phase status:** **PARTIAL / BLOCKED for production exit gate** (no access to deployed runtime/DB copy and no latest-commit CI validation).

## Repo structure and observation

- Python FastAPI `backend/app/main.py`, 956 lines; 37 declared HTTP endpoints, inventory in `ROUTE-INVENTORY.csv`.
- Python `backend/app/db.py`, 403 lines; SQLite `PRAGMA journal_mode=WAL` and `BEGIN IMMEDIATE` during schema bootstrap.
- `backend/app/job_records.py`, 284 lines; incremental startup schema upgrades plus status/snapshot triggers.
- React 19 / Vite 6 frontend, `frontend/src/App.jsx` ~2739 lines; `activePage` switches `editor`, `jobs`, `infrastructure`, `settings`; no page router found in inspected source. User-side admin token uses memory-only `sessionToken` and custom `X-Internal-Token`; no email/password accounts.
- `frontend/src/App.jsx` stores drafts, seed modes and presets in localStorage with workflow identifier **but without account ID**; potentially cross-account browser state when login arrives.
- `salad-worker/pull_worker.py` uses separate `DIRECT_WORKER_TOKEN` (`X-Worker-Token`) and direct-queue lease/heartbeat contract.
- `docker-compose.yml`: backend (`127.0.0.1:8100:8000`), frontend (`127.0.0.1:3100:80`), scheduler **profile `direct`**; volume `controller_data:/app/data` shared with scheduler. `.env.example`: `DB_PATH=/app/data/controller.db`. Effective server env/volume not inspected.
- `README.md` states worker excluded from repository, but actual tree includes `salad-worker/`; README is stale and must not override observed source. `docs/axis-07.md` explicitly labels the product *single-operator*.
- Repo Actions policy `.github/workflows/test-direct-queue.yml`: Python 3.12; Node 22; pytest with `PYTHONPATH=backend`; node --test; compileall; Vite build. `build-salad-worker.yml` builds GHCR tag `ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8-direct-v1` but **tag is not a deployed image digest**.

## GitHub CI evidence

- GitHub `actions/runs?head_sha=bea004d97a264f892cfae6dec9c4f691aed40a39` returned `total_count: 0` at inspection time; latest SHA therefore has **NO VERIFIED CI**.
- Public main-branch query exposed completed successful `Build Salad GPU Worker` run `37104797480` on SHA `54686dd3a3afd8151812bf58c318fe8a1f90a2c6` (2026-10-03); it is an **older commit** and proves nothing about this current SHA.
- Commit combined-status endpoint returned `pending`, `total_count: 0` (no reported statuses). This is **not PASS**.
- There was no local copy of repository files in the sandbox; direct clone failed because `github.com` DNS was unavailable in container. No current-revision npm/pytest/shell jobs were executed locally. Test status remains **NOT RUN**.

## Current auth & data isolation

- `main.py` `check_admin_token`: rejects private operations with `503` if `APP_INTERNAL_TOKEN` absent; otherwise checks one shared token using compare_digest. All 27 non-public, non-worker endpoints require this shared token. Seven Worker endpoints use an independent service token.
- `main.py` `/health`, `/api/workflows`, `/api/catalog` are public (the latter two should expose sanitized catalog only). There are **37** routes: 3 public + 27 admin-token + 7 worker-token.
- `db.py:create_job` inserts `owner='controller'` for new snapshotted jobs and NULL for non-snapshotted legacy jobs; this is **not a user FK**.
- `job_records.py` has partial unique index `jobs(client_request_id)`, global across all users. A future multi-user system requires `(owner_user_id, client_request_id)` plus payload-hash conflict validation.
- `input_assets` and `job_assets` have no `owner_user_id`; IDOR boundary is not available yet. Actual ownerless *row counts* require the operational DB copy and are **UNKNOWN**.
- `GET /api/jobs/{local_id}/assets/{asset_id}/download` checks shared token, verifies job/asset association, `available` and `outputs/{local_id}/` storage prefix, streams original with no-store headers. **Those checks are good for current single-operator mode but cannot enforce user A vs B.**

## Production environment comparison — NOT VERIFIED

| Subject | Repository evidence | Operational evidence | Gate |
|---|---|---|---|
| Server checked-out SHA | `bea004d97a264f892cfae6dec9c4f691aed40a39` | Not accessible | BLOCKED |
| Compose service runtime | declared in `docker-compose.yml` | No docker ps/config evidence | BLOCKED |
| SQLite volume and journal | `controller_data`, WAL source config | No safe DB copy or integrity results | BLOCKED |
| Current provider/Salad group | env+SQLite settings, not hard-coded source-of-truth | No provider read-only credentials | BLOCKED |
| Live GHCR digest | workflow publishes `fp8-direct-v1` tag | No image manifest or deployed digest | BLOCKED |
| R2 objects, permissions, key prefixes | uploads `inputs/{upload_id}/...`, outputs `outputs/{job_id}/...` | No list-only inventory | BLOCKED |
| Model cache and GPU VRAM | source/README examples only | No verified Worker handshake/manifest | BLOCKED |
| Browser 360px/keyboard screenshots | React/CSS source inspected | No live browser/environment/screenshots | NOT RUN |

## Deliverables and evidence classification

- **Completed (repository-static):** pinned SHA; route inventory; proposed policy; schema inventory of *code-created tables*; threat model; seven OPEN ADRs; feature-flag, rollout and rollback plans; read-only audit harness/tests.
- **Passed (offline synthetic only):** read-only SQLite access; backup/restore with a small **synthetic** WAL-mode fixture; object-list pagination using fake R2 client. These DO NOT prove production DB/Worker safety.
- **Blocked / not performed:** run repository tests on actual checkout, production-schema/row counts, restore from safe copy of operational SQLite, R2 inventory, deployed tag/digest comparison, real GPU E2E, CI for HEAD, UI browser capture.

**Caution:** documents and older CI runs represent plans/history, not proof of current staging/production readiness. Do not deploy based on this report alone.

## Source links

- [main.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/main.py) · [db.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/db.py) · [job_records.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/job_records.py)
- [App.jsx](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/frontend/src/App.jsx) · [direct_queue.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/direct_queue.py) · [Worker](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/salad-worker/pull_worker.py)
- [Compose](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/docker-compose.yml) · [env example](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/.env.example) · [CI YAML](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/.github/workflows/test-direct-queue.yml)

**Unavailable required inputs:** `GLOBAL-RULES.txt`, `DECISIONS.md`, prior HANDOFF, full `MASTER-SPECIFICATION.txt` were requested in the provided execution prompt but were not attached and are not present in the observed GitHub tree. The supplied `SOURCE-EXCERPTS.txt`, `SPEC.txt`, `ACCEPTANCE-TESTS.txt`, execution prompt, and two project PDFs were used as available project design context. Conflicting decisions are intentionally left OPEN, not silently approved.
