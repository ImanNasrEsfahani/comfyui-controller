# Database inventory — source schema only

Observed source: [db.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/db.py) and [job_records.py](https://github.com/ImanNasrEsfahani/comfyui-controller/blob/bea004d97a264f892cfae6dec9c4f691aed40a39/backend/app/job_records.py) at `bea004d97a264f892cfae6dec9c4f691aed40a39`. This is the **code-declared target after startup migrations**, NOT a dump or read of the deployed SQLite file.

| Table | Key columns/role | Ownership observation |
|---|---|---|
| workflows | id, name, api_prompt, ui_workflow, capabilities_json, created_at, updated_at | no owner_user_id |
| jobs | id, workflow_id, state, request_json, snapshot_json, variables_json, client_request_id, request_hash, owner, source_job_id, execution_mode, lease fields | `owner TEXT` nullable, not FK; new snapshotted jobs often 'controller' |
| controller_settings | key, value | global settings, secrets must not be exported |
| job_attempts | id, job_id, sequence, previous_attempt_id, worker_id, lease_token_hash, state | foreign identity links not declared FK in CREATE |
| job_assets | asset_id, job_id, attempt_id, storage_key, mime_type, status, verified_at, media info | no owner_user_id |
| input_assets | asset_id, storage_key, mime_type, dimensions, size_bytes | no owner_user_id |
| job_events | job_id, version, attempt_id, previous_state, state, reason, observed_at | linked indirectly through job |
| job_progress | job_id, attempt_id, sequence, phase, value, total, source | linked indirectly through job |
| job_progress_events | job_id, attempt_id, sequence, phase, value, total, source | linked indirectly through job |
| instance_observations | group_name, version, updated_at, snapshot_json | system scope |
| instance_sessions | session_id, group_name, instance_id, timestamps, intervals_json | system scope |
| instance_cost_periods | period_id, session_id, hourly_rate, currency, source, timestamps | system scope |
| instance_stage_events | event_id, group_name, instance_id, stage, observed_at | system scope |
| instance_operations | operation_id, group_name, action, status, timestamps | system scope |

**14 tables** identified. Note source uses on-startup additive migrations (`ALTER TABLE`), not yet versioned Alembic revision tracking. Important indexes: `idx_jobs_direct_queue`, unique partial `idx_jobs_client_request` (global), `idx_job_assets_storage_key`, `idx_job_progress_attempt`, `idx_job_progress_events_recent`, `idx_instance_active_session`, `idx_instance_cost_session`, `idx_instance_stage_events_recent`, `idx_instance_operations_recent`.

**Triggers:** `jobs_snapshot_immutable`, `jobs_transition_guard` (replaced during `migrate`), `jobs_success_requires_assets`, `jobs_insert_event`, `jobs_record_version`. Implementing Owner migration must preserve triggers and transaction boundaries.

`PRAGMA journal_mode=WAL` and `BEGIN IMMEDIATE` exist in `init_db`. `connect()` configures 5-second busy timeout; foreign-key enforcement is not explicitly enabled in `connect()` (SQLite defaults often OFF). **Do not assume FK enforcement until runtime PRAGMA is inspected.**

### Actual deployed data: unknown

- No operational SQLite file was provided. Table counts, actual columns/index/triggers, `PRAGMA foreign_keys`, data consistency, existing legacy `owner` distribution and orphan references are **NOT RUN/UNKNOWN**.
- Run the included `phase00_db_audit.py` on an authorized **isolated consistent SQLite copy**. The JSON report inspects sqlite_master, table counts, PRAGMA table_info/index_list/foreign_key_list, owner NULL/empty counts, and integrity without returning private rows.
- Use temporary synthetic data only for automated proof; a synthetic success does NOT count as real-data recovery verification.

### Legacy mapping design (not executed)

1. Identify original single-operator account under owner-approved email/ID and verify account ownership before migration.
2. Freeze writes or use SQLite online backup and evaluate concurrent Worker callbacks. Record counts/hash in **isolated copy**.
3. Create stable users/roles/session schema with versioned migration, assign old `jobs` and related assets to legacy admin only when provenance proves linkage.
4. Unresolved owners -> quarantine (private, no account can access by default); never interpret NULL as public.
5. Enforce owner FK NOT NULL only after backfill and orphan audit; index `(owner_user_id,created_at)` and `(owner_user_id,client_request_id)`.
6. Preserve original snapshots, job IDs, Attempt relations, output keys, compatibility with old Worker callbacks, and rollback DB copy.
7. Run A/B access tests, real asset signed URL authorization and restore again before enabling new login.

PostgreSQL is a candidate for future multi-user production; move only with benchmark and rollback approval (ADR-02 OPEN). No production migration authorized in Phase 00.
