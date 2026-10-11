# Phase01 SQLite schema dictionary and invariants

**Revisions:** `001_identity`, `002_owner_columns`, `003_legacy_review`. Optional manual `004_scoped_keys` after both legacy helpers are source-patched.

**New tables:** `schema_migrations`, `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `sessions`, `email_verification_tokens`, `password_reset_tokens`, `mfa_methods`, `mfa_recovery_codes`, `auth_events`, `user_preferences`, `presets`, `idempotency_keys`, `legacy_owner_approvals`, `owner_review_queue`.

**Altered legacy tables:** `jobs`, `input_assets`, `job_assets` gain nullable `owner_user_id REFERENCES users(id)` and not-null `ownership_state DEFAULT 'unclaimed'`. Migration does not rewrite media storage keys or delete rows, Attempts, Progress or existing Job snapshot/transition triggers.

**Invariants:**

- DAO requires `(owner_user_id = validated_actor AND ownership_state='verified')` in SQL for every object read. Job output additionally joins verified parent Job same owner.
- Any unclaimed historical Job/Asset is placed in `owner_review_queue` with `status=quarantined` (a metadata workflow state, not a destructive physical relocation).
- Record with `ownership_state=verified` and `owner_user_id IS NULL` is rejected by triggers. FK rejects invented users. `NOT NULL owner_user_id` is postponed until verified real backfill, old writes upgraded and full staging tests.
- `idempotency_keys` uses composite primary key `(owner_user_id,client_key)` and associates each owner with a verified Job. `idx_jobs_owner_request` is additive; global legacy `idx_jobs_client_request` stays until optional phase 004 activation. `idx_jobs_legacy_request` retains uniqueness for null-owner legacy flow after activation.
- Legacy approval is explicit: active, email-verified original operator, evidence ref/approver/SHA, no inferred match. Input assets lacking provable Job ownership and orphan outputs remain unclaimed. Existing `request_json`, `variables_json`, `snapshot_json` untouched.
- Secrets: only salted Argon2id password hash and SHA256 session-token digest in DB; no plaintext session or verification/reset tokens. No raw uploaded image, prompt or API token in audit logs.

**Recommended eventual constraints:** `NOT NULL owner_user_id` and user ownership foreign keys are not globally enforceable without verified mapping, old worker/legacy writes migration and concurrency-sensitive cutover. In phase01 they remain nullable with fail-closed DAO.
