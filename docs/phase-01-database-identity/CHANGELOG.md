# CHANGELOG — Phase01

New, additive `migrations/phase01.py`: `001_identity`, `002_owner_columns`, `003_legacy_review`; user/roles/permissions/session/verification/reset/MFA/preferences/admin-proof registry, nullable owner FK columns and indexes on jobs/input_assets/job_assets, source linked review quarantine; down for empty copy only. Existing tables/triggers/job state logic preserved; SQL migration is **opt-in**.

New `identity_repository.py`: SQL-filtered owner queries for jobs, assets, presets, Argon2id, hashed sessions, per-owner idempotency mapping, approval-aware legacy owner selection. New CLI scripts for online SQLite backup/migrate/downgrade/secure-admin bootstrapping. `backend/requirements.txt` extended only for Argon2id. New security migration tests and documentation. An SHA-pinned local patch generator can update two existing legacy source files for a later coordinated staging deployment.

NOT changed: FastAPI routes, main.py, frontend, Worker/Salad, R2 objects, real DB, GitHub. NOT approved: legacy-admin backfill, public registration, migrations on production, any GPU operation. No secrets, prompts, object keys or private images added.
