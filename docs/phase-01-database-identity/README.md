# Phase 01 — Database Identity & Ownership (COPY/STAGING only)

**Source repo:** `ImanNasrEsfahani/comfyui-controller` (read-only)

**Pinned latest main SHA:** `48b0bb50fe3cd582f37e9049a3988a83db9c4a24` (one documentation-only commit ahead of Phase00 base `bea004d...`).

**Phase status: PARTIAL / BLOCKED FOR RELEASE.** The Phase00 HANDOFF explicitly marked full baseline/restore as blocked, its architecture ADRs all `OPEN`, and the required `GLOBAL-RULES.txt`, `DECISIONS.md`, an approved `LEGACY_OWNER_PLAN` and a consistent production SQLite backup were not available. This ZIP therefore is an **offline implementation package**, not a production deployment.

## Contents (repository-relative)

- `backend/app/migrations/__init__.py`, `phase01.py`: SQLite numbered revisions, identity/role/session tables, nullable owner FKs, quarantined legacy review, scoped indexes, online SQLite backup API, gated legacy ownership function, optional scoped-key activation, reversible empty-copy downgrade.
- `backend/app/identity_repository.py`: Argon2id password helper, admin seed primitive, opaque hashed session/token primitives, SQL-scoped access for Job/Input Asset/Job Asset/Preset, per-user idempotency mapping.
- `backend/requirements.txt`: **full replacement** that adds pinned `argon2-cffi==25.1.0` to previous 6 dependencies.
- `scripts/phase01_database.py`: copy-only migrate/backup/downgrade; never auto-runs on backend startup.
- `scripts/phase01_seed_admin.py`: interactive test-copy-only admin bootstrap, no hard-coded secret.
- `scripts/phase01_prepare_checkout.py`: strict source-Git-blob-pinned installer, which reconstructs **two local full replacement files** (`backend/app/db.py`, `backend/app/job_records.py`) in the user's real checkout; no GitHub writes. This is necessary because the repository can only be read via connector, not fetched into the isolated local filesystem of this run. It must not be used on production until a separate migration/cutover window.
- `tests/test_phase01_identity.py`: synthetic Legacy SQLite + security/SQL/restore tests.

## Important distinction

Unzipping does **not** rewrite existing `db.py` or `job_records.py`. Their integration is provided by a strict SHA-checked local installer because full source bytes could not be materialized in this runtime. User must review its output with `git diff` before considering any deployment. It will refuse unknown/newer versions rather than blindly patch them.

No new `/login`, `/register`, `/api/auth/*`, frontend user shell, CSRF or email delivery is added; these are explicitly outside Phase01 scope. The old controller token endpoints remain unchanged at the HTTP layer and are NOT safe for untrusted multi-user access. Do not advertise account login or private user galleries yet.

## Status summary

| Scope | Local result | Production/staging gate |
|---|---|---|
| M001 identity/roles/session/token tables | Implemented; synthetic migrations PASS | DB engine ADR OPEN, staging NOT RUN |
| M002 owner refs/jobs/asset rows/presets | Nullable owner FK/indexes and default unclaimed PASS | No approved owner backfill or NOT NULL |
| M003 unclaimed-record quarantine | Auto-review records PASS on synthetic | Real orphan counts unknown |
| Owner-scoped DAO and sessions | Synthetic A/B negative queries PASS | No HTTP current_user integration (out of scope) |
| Legacy admin bootstrap | Argon2id/role/hashed sessions PASS on synthetic | No real owner or email verification approval |
| Per-owner idempotency | Per-owner mapping and staged new index PASS on synthetic | Legacy schema global index remains by default; activation blocked |
| Old Job Worker/Cancel/Retry/History | Source intentionally preserved | Real repository regression NOT RUN in this container |
| Restore / rollback | Synthetic online copy, downgrade PASS | Real DBA backup & restore NOT RUN |

## Non-negotiable release holds

1. Obtain approved `GLOBAL-RULES.txt`, `DECISIONS.md`, source Master and confirmed Phase00 baseline and owner plan. Human product owner must explicitly approve original admin account mapping.
2. Safely capture live SQLite using online backup API, collect pre/post schema, counts, orphan and signed-URL access inventory, snapshot worker image and active leases, rehearse copy restore. **No** raw private DB in public CI artifacts.
3. Test on a clone of **actual** deployed SQLite schema with full `PYTHONPATH=backend python -m pytest -q tests tests/check_frontend_backend_upgrade.py`, `node --test tests/*.mjs`, frontend npm build, Browser E2E and Worker flows. Block release on any regression.
4. Re-check current Git SHA and deploy files match pinned source. Run installer only after verifying the migration/cutover sequence and patch with representative real DB copy.
5. Do not activate user-facing multiuser route until actual server authorization + session cookie/CSRF and 20 A/B direct HTTP tests PASS. Fail closed on any ownerless asset.

## Next phase handoff

Build session-based `current_actor` & CSRF middleware, user-specific API routes, explicit per-owner SQL in actual handlers, Email workflows and Frontend account state after this foundation has been staged and audited. Keep Worker service token isolated and old Jobs visible only to authorized verified legacy owner.
