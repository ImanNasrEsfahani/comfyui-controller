# Phase10 changed-file changelog

Base main `d51a4eac487bee4f69808a9e8d49016fcafe624a`.

- Added `backend/app/studio_api.py` with strictly typed partial-draft structural validator, filtered allowlisted node catalog, per-role access and CSRF, no-store cache policy, revision-aware saves, revision-aware validate, non-executing compile preview, metadata-only gated publish, restore-as-new-version, gated unpublish and audited changes.
- Added additive `backend/app/migrations/phase10.py`, isolated editor graph/layout/viewport state and atomic revision checks (BEGIN IMMEDIATE). Phase09 immutable compiled/published snapshots remain unchanged.
- Extended only existing `backend/app/workflow_api.py` to mount the Studio sub-router inside the existing opt-in Phase09 router; legacy `main.py` unchanged in replacement ZIP.
- Added React `WorkflowCanvas.jsx` node canvas, typed wire drawing, drag+keyboard movement, zoom controls, minimap; pure editor helpers in `graphEdit.mjs` with typed edges, cycle checks, undo/redo and diff.
- Added `StudioV2.jsx`, `studioClient.js`, `studio.css`; changed frontend router + route guard only, selecting new UI when `VITE_WORKFLOW_STUDIO_ENABLED=true`; legacy Phase09 views retained otherwise.
- Added safe complete-snapshot compile summary only; never returns graph execution payload, prompt, temporary URL or storage key.
- Added Phase10 unit/HTTP/SQLite regression tests, copy-only migrator, read-only-source-pinned composite backend mount installer and verification tool, `.env` example and release documentation.

No React package changes, no arbitrary user JSON upload, no worker files changed, no provider API calls, no schema automatic migration, no GitHub writes.
