# UI / Worker / runtime static audit

**Observed repository (not a browser or provider audit):**

## Frontend

`frontend/src/App.jsx` holds ~2739 lines; `activePage` chooses `editor`, `jobs`, `infrastructure`, `settings`, rather than independent React Router URLs. The app holds `sessionToken` in module memory only and adds `X-Internal-Token` to authorized fetches. LocalStorage uses keys `comfyui-controller:variables:${workflowId}`, `:seed-mode:${workflowId}`, and `:presets:${workflowId}`; SessionStorage uses `:pending-request`. Saving image URLs is deliberately avoided, but keys are not owner-scoped. Risks: A/B account switch on shared device; stale draft/preset state; registration migration with cookie sessions.

Existing logic to keep/evaluate before refactor: Upload and reference processing (revision/AbortController), Workflow variable editing and validation, seed/preset handling, submitted Job and progress details, jobs/history, settings/instance panel, preview/lightbox. None is a guaranteed independently reusable component until code is split. Recommended gradual extraction: request/auth wrapper, workflow-bound variable form, uploads, jobs and instance state; then proper router layouts. No Big Bang rewrite.

**Visual baseline:** 360px layout, mobile touch target, browser screen-reader flow, keyboard focus, text direction and screenshots could NOT be tested; no deployed UI/session available. No screenshots claimed.

## Worker and scheduler

`salad-worker/pull_worker.py` receives separate `DIRECT_WORKER_TOKEN` from private environment and sends `X-Worker-Token` to backend. It uses local ComfyUI `/prompt`, `/system_stats`, attempt-specific lease token, heartbeat and progress callbacks. WebSocket import is optional and numerical progress should not be assumed when absent. Current worker checks runtime service readiness, not selected model readiness. `backend/app/direct_queue.py` performs fenced leases and attempt checks; `direct_scheduler.py` reasons about pending, running, finalizing, HOLD and idle lifecycle. These mechanisms should be preserved through v2 migration and revalidated on real GPU.

`docker-compose.yml` defines `scheduler` only under `profiles: [direct]`; without that profile it is not running by default. Volume `controller_data` mounted `/app/data`, `.env.example` defaults `DB_PATH=/app/data/controller.db`. Deployed status of the scheduler, exact profile, Replica count and provider billing are unknown.

## Source/build drift to resolve

- README says repo excludes Salad Worker; current tree includes `salad-worker/`.
- `.github/workflows/build-salad-worker.yml` publishes tag `ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8-direct-v1`; a tag is not the immutable digest of a currently deployed container.
- `salad-worker/README.md` describes earlier deployment examples (e.g. queue and group). Current `.env` and SQLite settings are authoritative for deployed runtime; old docs do not prove actual live names.
- Last observed SHA has no verified passing CI. Run exact backend/frontend tests on a genuine checkout and compare Live code SHA, Worker Digest, Schema and R2 counts before Phase 01.
