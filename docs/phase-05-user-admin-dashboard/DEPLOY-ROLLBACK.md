# Phase05 — Staging install and rollback, **NOT PRODUCTION**

**Never enable multi-user production on this package alone.** Approved owner-backfill, backup/restore and Phase03 atomic owner-safe Generate/Retry are absent; Phase04 end-to-end security and UI regression tests are not finished. STOP if SHA differs.

1. In a disposable staging checkout of `https://github.com/ImanNasrEsfahani/comfyui-controller`, verify `git rev-parse HEAD` **equals** `1593039f9239db6e757b633b28477aa29d6a71c2` before copying.
2. Extract the ZIP at repo root, replacing only files with matching paths; review diff. Do not alter private `.env` or secrets.
3. Run `python3 scripts/phase05_prepare_checkout.py` (dry run). If successful, run `python3 scripts/phase05_prepare_checkout.py --apply` in the checkout. This installs Phase02/Phase03/Phase05 routers in `main.py`; **no GPU, DB, or server operation**. It aborts on changed SHA or unexpected blob.
4. Create a WAL-consistent backup / restored **isolated DB copy**, outside Production. Run previous Phase01/02 migrations if missing (only on the copy) and verify legacy owner inventory. Then run `python3 scripts/phase05_migrate_copy.py --db-copy /path/to/isolated.sqlite --acknowledge-offline-copy`. Run `PRAGMA integrity_check`, FK, and row count diff; test restore after migration. Never point this CLI at an active database.
5. On staging with fake emails and synthetic users, run:
```
python3 -m compileall -q backend/app
PYTHONPATH=backend python3 -m pytest -q tests
node --test tests/*.mjs
npm --prefix frontend ci  # or npm install if lockfile absent; use trusted registry only
npm --prefix frontend run build
```
6. Only with an approved release plan/verified staging and HTTPS origin may operators consider private staging flags in their secret store: `AUTH_ENABLED=true`, `OWNER_ISOLATION_ENABLED=true`, `ACCOUNT_UI_ENABLED=true`, `AUTH_REGISTRATION_MODE=invite`, matching `AUTH_PUBLIC_ORIGIN`, strong `AUTH_CSRF_SECRET`, and frontend `VITE_AUTH_UI_ENABLED=true`. Keep `ACCOUNT_REQUESTS_ENABLED=false` until a human review queue exists. Do NOT expose APP_INTERNAL_TOKEN or service tokens to authenticated Users.
7. Recheck A/B and IDOR matrix, suspended session on second device, rollback, no browser admin-token, actual SMTP and proxy/Cookie/CSRF behavior. Production release remains blocked until all mandatory Phase00-04 checks are verified.

Rollback staging: first turn off `ACCOUNT_UI_ENABLED`, `VITE_AUTH_UI_ENABLED` and `ACCOUNT_REQUESTS_ENABLED`; restore previous frontend assets and application files from exact git revision (or move staging service back to pinned known-good Docker digest). Schema change is additive; no automatic down migration. If DB rollback is necessary, restore previously verified WAL-consistent snapshot **only with writers/worker leases safely quiesced**, never delete or mutate actual user data by guessing ownership. The migration has no hard delete, reassign or overwrite semantics.
