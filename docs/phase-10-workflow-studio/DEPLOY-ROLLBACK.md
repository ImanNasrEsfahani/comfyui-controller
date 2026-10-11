# Phase10 — staging-only deployment & recovery

**Do not apply to production until the release gates pass.** Read-only source commit: `d51a4eac487bee4f69808a9e8d49016fcafe624a`. The ZIP holds only new/modified files. No destructive operations or database/R2 modifications were performed here.

1. On a disposable Git checkout of exact `main` SHA, confirm `git rev-parse HEAD` equals base. Save separate backup of working tree, active environment, SQLite DB (SQLite backup API) and deployment manifests; never overwrite existing backups.
2. Overlay the ZIP paths exactly. Verify `PHASE10-PATCH-MANIFEST.json` hashes via `python scripts/phase10_verify_checkout.py --repo . --manifest PHASE10-PATCH-MANIFEST.json` (checks exact source HEAD and changed bytes).
3. On a **copy only** of a Phase09-migrated SQLite database, run:

   ```sh
   python scripts/phase10_migrate_copy.py --source /secure/offline-phase09.sqlite --copy /secure/phase10-staging.sqlite
   ```

   Confirm checksum in `schema_migrations`, `PRAGMA integrity_check` and FK check. Do not point application to a live DB on this step.
4. `backend/app/main.py` was **not** replaced directly. The existing GitHub `main.py` is still the legacy original. To compose the additive router mounts from the prior reviewed installers, on exact checkout first run:

   ```sh
   python scripts/phase10_prepare_checkout.py --repo .
   ```

   Then only after reviewing the expected transformations run `--apply`; this preserves `.phase10.bak` files. Inspect `git diff -- backend/app/main.py backend/app/job_records.py`, rerun all Stage00-10 tests and verify all existing legacy routes. If any anchor mismatches or SHA changed, STOP; do not bypass hash checks.
5. On a disposable **staging frontend build only**, configure `VITE_AUTH_UI_ENABLED=true`, `VITE_WORKFLOW_STUDIO_ENABLED=true`; on isolated backend only, `WORKFLOW_COMPILER_ENABLED=true`, `WORKFLOW_STUDIO_ENABLED=true` (others remain false). Use real test accounts, no production secrets, no Salad group connected, no GPU request authorization. Retain default OFF otherwise.
6. Validate staged A/B ownership and CSRF, large graph, concurrency/two-tab `409`, published immutability, responsive 360px, keyboard/screen reader, refresh/back navigation, and full React/Vite build. A graph showing `runtime_verified:false` must **never** be sent to worker.

**Rollback:** Set Phase10 flags OFF in both application configurations, redeploy prior frontend artifact, and stop using Stage10 API. For a disposable local checkout only, restore backed-up `main.py` and `job_records.py` after confirming file provenance. Preserve additive `studio_drafts` table for forensics; do NOT run destructive table drops, do NOT roll back published Phase09 data. Restore disposable SQLite snapshot if migrations fail. Never delete old Worker image or historical graph data.
