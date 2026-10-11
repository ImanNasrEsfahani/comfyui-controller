# Phase 02 — Implementation changelog

Baseline: `3f749b52d375188e8844d68c42485db6668d928c` (latest main at audit time, after Phase01 commit).

## Changed/new files
- NEW `backend/app/auth.py`: isolated FastAPI router with registration (invite/public/disabled), email verification + resend, login, logout/all, sessions/revoke, forgot/reset/change password, safe user and CSRF endpoints. User sessions do not grant legacy admin or worker access.
- NEW `backend/app/security.py`: DB-bound opaque Secure/HttpOnly/SameSite=Lax `__Host-` session, CSRF origin+HMAC token, idle/absolute expiry, role dependency and generic safe user contract.
- NEW `backend/app/auth_mail.py`: SMTP TLS interface, overrideable fake mailer in tests, non-sensitive transport errors.
- NEW `backend/app/migrations/phase02.py`: explicit checksum-guarded 004_auth_policy migration; hashed invitation keys, rate limit counters; requires Phase01.
- NEW `backend/auth.env.example`: safe disabled-by-default configuration template; no credentials.
- NEW `scripts/phase02_apply_checkout.py`: SHA and Git blob pinned local patch for `backend/app/main.py` (two insertion lines); never modifies GitHub.
- NEW `scripts/phase02_database.py`: SQLite online-backup API source->NEW COPY then Phase02 additive migration; no in-place production writes.
- NEW `scripts/phase02_invite.py`: invite token hashes in DB; one-time plaintext in operator-only 0600 file.
- NEW `tests/test_phase02_auth.py`: offline FastAPI TestClient suite with fake SMTP and synthetic SQLite Phase01+Phase02 schema.
- NEW docs: TEST-REPORT, DEPLOY-ROLLBACK, API-CONTRACT, HANDOFF, RELEASE-GATE.

## Existing code intentionally unchanged
- `backend/app/db.py`, `job_records.py`, `direct_queue.py`, `salad-worker/*`, `frontend/*`, `backend/requirements.txt` (already contains `argon2-cffi==25.1.0` at baseline).
- `backend/app/main.py` is not reproduced blindly; source-checked local installer changes it in the operator's full checkout.  **This ZIP alone does not mount auth routes until the installer runs.**

## Scope exclusions
- Auth pages and user-scoped Jobs/Assets routes are Phase04/Phase03; MFA enrollment/TOTP/recovery not enabled or represented as tested.
- No production DB migration, email send, new admin creation, provider operation, GitHub modification or destructive action performed.
