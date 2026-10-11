# Phase03 staging-only installation / rollback

**DO NOT DEPLOY TO PRODUCTION OR ENABLE PUBLIC REGISTRATION NOW.** Approved `GLOBAL-RULES.txt`, `DECISIONS.md`, `LEGACY_OWNER_PLAN` and Phase01/02 DONE_VERIFIED evidence are missing. Generating/retrying new user jobs is explicitly disabled; so turning on this flag in production would break normal generation.

### Install in a disposable copy of exact GitHub checkout
```
git clone https://github.com/ImanNasrEsfahani/comfyui-controller.git phase03-staging-copy
cd phase03-staging-copy
git rev-parse HEAD   # MUST equal 2738df39a17b5f93c61ada6b955a56d121dc7101
# Unpack ZIP into checkout root (paths preserved). Avoid overwriting .env.
python3 scripts/phase03_prepare_checkout.py   # dry-run, verifies both blob hashes
python3 scripts/phase03_prepare_checkout.py --apply
python3 -m compileall -q backend/app
python3 -m pip install -r backend/requirements.txt pytest
PYTHONPATH=backend python3 -m pytest -q tests tests/check_frontend_backend_upgrade.py
node --test tests/*.mjs
npm --prefix frontend install --no-audit --no-fund
npm --prefix frontend run build
```

Check source diff and full test logs. Do not enable `OWNER_ISOLATION_ENABLED` if any test fails. Phase02's opt-in migrations (`phase01`, `phase02`) MUST be run on a SQLite **copy** only after WAL-safe backup/restore rehearsal. Ensure all relevant output assets are verified owner-bound and quarantined orphan counts resolved. Do NOT run `phase03_prepare_checkout.py` after unrelated edits: it will refuse unrecognized blob SHA. This package includes NO automatic migration or backfill.

To rehearse behind an isolated staging HTTPS origin, explicitly set in *private staging env* `AUTH_ENABLED=true`, `OWNER_ISOLATION_ENABLED=true`, `AUTH_REGISTRATION_MODE=invite`, verified `AUTH_CSRF_SECRET` and matching `AUTH_PUBLIC_ORIGIN`. Do not use shared production secrets. Under this flag, user API is read/download/upload/cancel/hide-only; Generate/Retry intentionally return 503. Existing frontend still uses legacy X-Internal-Token until Phase04; do NOT expose it to normal users.

### Rollback and cutover rules
- Roll back feature flag to `false` only if trusted legacy single-operator mode is acceptable; do not use as emergency public multi-user mode.
- Revert generated `main.py`/`job_records.py` and added modules via version control in the staging checkout. The patcher itself makes no DB schema changes.
- Keep SQLite backup+WAL-safe restore and previous Docker image available; never restore a DB with active un-fenced Writer/Worker jobs.
- Require real A/B direct HTTP tests, R2/private ACL check, Worker completion, verified admin audit policy, full frontend switching, `Generate->Download`, and owner-safe retry before publishing user accounts.
