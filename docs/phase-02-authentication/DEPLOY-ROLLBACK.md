# Deployment / rollback runbook — NO production authorization

**DO NOT enable authentication in production until Phase00/01 release blockers are cleared:** approved `DECISIONS.md` / `GLOBAL-RULES.txt`, actual DB backup+restore drill, signed `LEGACY_OWNER_PLAN`, real email SMTP, Phase01 owner migration and full checkout regressions.

## Review and install on a checkout at exactly the recorded SHA
```bash
cd /var/www/comfyui-controller
# Review the latest main SHA; abort if it is different from source baseline in CHANGELOG.
git rev-parse HEAD
# Copy ZIP files over checkout preserving relative paths, excluding docs if desired.
# With all ZIP contents extracted into this checkout:
python3 scripts/phase02_apply_checkout.py .
git diff -- backend/app/main.py
python3 -m compileall -q backend/app
PYTHONPATH=backend python3 -m pytest -q tests/test_phase02_auth.py
# Recommended: run the full regression from .github/workflows/test-direct-queue.yml.
PYTHONPATH=backend python3 -m pytest -q tests tests/check_frontend_backend_upgrade.py
node --test tests/*.mjs
npm --prefix frontend install --no-audit --no-fund
npm --prefix frontend run build
```

## Offline schema rehearsal (no live changes)
```bash
# SOURCE must be an actual SQLite-consistent snapshot, not a raw copy of a hot WAL file.
python3 scripts/phase02_database.py --source /private/snapshots/controller-phase01.db --copy /private/staging/controller-phase02.db
# Inspect with sqlite3 shell: PRAGMA foreign_key_check; SELECT revision FROM schema_migrations;
# Counts must match across jobs, workflows, input_assets, job_assets and users.
```
Do not directly copy the live DB file while WAL is active. This tool uses SQLite backup API in read-only mode and never mutates source. Target must not exist. Phase01 must already be applied to the source. A *separate reviewed production plan* is required to migrate production with explicit maintenance/drain, real restore verification and rollback criterion; this ZIP intentionally has no `--in-place` mode.

## Enable only in approved staging
Create strong `AUTH_CSRF_SECRET` in private environment (>=32 chars). Set `AUTH_PUBLIC_ORIGIN=https://...` to actual HTTPS origin; no trailing path. Configure `AUTH_SMTP_*` TLS credentials privately; verify SPF/DKIM/DMARC and deliverability. Keep `APP_INTERNAL_TOKEN` and `DIRECT_WORKER_TOKEN` in server-only environment; never copy them into frontend. `AUTH_REGISTRATION_MODE=invite` default. Keep `AUTH_ENABLED=false` until schema+SMTP+CSRF+test checks pass. For invitation, use `scripts/phase02_invite.py --db <staging-copy> --email <address> --token-file <private-path>` and securely hand out the one-time file contents; do not commit or upload raw token.

## Rollback
First set `AUTH_ENABLED=false` to block all session auth routes; old single-operator admin header/worker protocols have not changed. Do not delete Phase01/02 tables or any user/session/job data automatically. If source code must revert, restore Git checkout to the previous reviewed commit **only after** checking DB compatibility; validate health and logs on staging. For DB rollback, restore the tested pre-change backup during a maintenance window; do not use destructive `DROP TABLE` blindly. Session cookies are invalid if rollback loses corresponding session rows.

## Release hold
Pending: live DB backup/restore, approved account ownership, provider SMTP deliverability, DNS/SPF/DKIM/DMARC, HTTPS+Cloudflare origin, CI and frontend full main integration, two-user security matrix, MFA choice. No production deployment or GPU run was performed.
