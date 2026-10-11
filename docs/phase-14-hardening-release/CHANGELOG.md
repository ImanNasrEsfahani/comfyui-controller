# Phase 14 — Change log

**Base SHA:** `8a591a3e501ba5a09751659357c625ac05babaf0`.

### Added

- A **non-deploying** GitHub Actions QA workflow for backend/worker pytest, JS tests, frontend Vite build, syntax, release gate and API import inventory. It uses minimal repository read permissions and uploads sanitized summaries; no public credential, GPU or production provider interaction.
- Strict read-only source release inventory. All previous 14 HANDOFFs are assessed as `PARTIAL/BLOCKED`; missing approvals and independent release evidence remain `NOT RUN`.
- Offline SQLite copy/restore auditor: read-only Backup API snapshot into a temporary DB, `integrity_check`, `foreign_key_check`, table count parity, unassigned/unverified owner scans, and source fingerprint check.
- Static router and optional runtime FastAPI OpenAPI inventory. The legacy `main.py` still has zero `include_router` calls at this source SHA.
- Export-only SHA-guarded composite route/worker source transformer for local review. Full checkout transformation is not independently verified in this sandbox.
- Secret-redaction helper for test log artifacts; no false assertion of complete protection.
- Synthetic negative tests, Phase13 standalone regression rerun, review matrix, security gates, operator deploy/rollback and emergency runbooks.

### Intentionally not changed

- No live `backend/app/main.py`, `job_records.py`, old Worker, Dockerfile, database, R2 object, Salad deployment, and no feature-flag enablement.
- No `DONE_VERIFIED` claim, video model activation or user-facing production migration.
- No attempt to produce unapproved DEC-01…15 or forge independent staging evidence.
