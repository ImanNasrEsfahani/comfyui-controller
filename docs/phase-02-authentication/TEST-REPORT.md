# Phase02 implementation / test evidence

- Latest audited GitHub `main` at start and re-check: `3f749b52d375188e8844d68c42485db6668d928c` (`Phase 01 - developement`). `backend/app/main.py` Git blob `f3fc84226be8704e4ae4d63b63babb84ca0ea291` SHA-pinned by installer.
- Phase01 modules used by synthetic integration were byte-for-byte matched to GitHub blobs: `identity_repository.py` SHA `201273fd1341de669866530baf36ad23eee20751`, `migrations/phase01.py` SHA `77b3c82561b113516eb0587ec51667cb4ad7502f`.
- Runner Python 3.13.5; installed FastAPI/httpx/argon2/pytest; no external network calls, mail fake, HTTPS TestClient, disposable SQLite databases and no GPU provider.

| Item | Status | Evidence / limitation |
|---|---|---|
| FastAPI HTTP regression on synthetic Phase01 + Phase02 SQLite | PASS | 14/14 unittest; 14/14 pytest (see sanitized logs) |
| Registration->verify->login->session->logout | PASS offline | TestClient, mock email sender |
| One-time verification, reset, replay rejection, revoke sessions | PASS offline | Tokens hashed at rest; old password rejected |
| Cookie/CSRF/Origin negative tests | PASS offline | `__Host-`, Secure, HttpOnly, SameSite=Lax; origin mismatch blocked |
| Email enumeration / rate limit | PARTIAL | Generic forgot body and login statuses tested; SMTP real timing/outbox and distributed IP limits untested |
| Invite-only + concurrent registration | PASS offline | Race produced one row, two neutral responses; single-use invitation |
| Hashed session/token storage and Argon2 rehash | PASS offline | Synthetic DB inspection, no secret in test log |
| Role escalation and spoof | PARTIAL | Test-only session `require_role(admin)` rejects; real legacy/admin routes remain header-only and Phase03 authorization absent |
| Phase02 migration twice / FK integrity | PASS offline | Two runs idempotent, PRAGMA foreign_key_check empty |
| SQLite backup source->new copy migration | PASS offline | Target created; source stayed unchanged; new tables only in copy |
| Source-pinned `main.py` patch | NOT RUN on full checkout | Only checked anchors against connected GitHub and included SHA-pinned local installer |
| Full Python/JS/NPM regression on latest repo | NOT RUN | Full checkout not available in container; run workflow in checkout |
| Real SMTP, HTTPS proxy, cookie on actual domain, SPF/DKIM/DMARC | NOT RUN | No private provider credentials / staging access |
| Real database backup/restore, cross-account Job/Asset APIs, Salad/GPU | BLOCKED | Needs operator approval and future Phase03/04 |
| MFA (TOTP/recovery) | NOT IMPLEMENTED | AUTH_MFA_ENABLED defaults false. Remains a release choice |

**Release status: PARTIAL / BLOCKED.** No Phase02 release claim. Neither Phase00 nor Phase01 has been certified DONE_VERIFIED in production. Do not enable auth for live users until approved staging review.

Security notes: tests use only synthetic identities; secrets/passwords/tokens are not included in evidence or logs. A passing mocked test does NOT establish production readiness. Authentication is default-off and session-based User requests cannot call current admin or Worker endpoints with their cookie.
