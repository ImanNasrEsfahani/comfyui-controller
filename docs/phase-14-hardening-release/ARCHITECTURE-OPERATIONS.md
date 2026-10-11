# Architecture, data contracts, operations and observability

## Confirmed source architecture (not necessarily integrated runtime)

- Permanent frontend: React/Vite compiled to Nginx static container; backend: FastAPI; background optional `direct_scheduler`; SQLite mounted in Compose volume; GPU Worker is a separate Salad container. R2 is the private object store.
- Phases 01–13 add opt-in auth/session tables, owner-aware Job/Asset relations, Model/Worker Image/Deployment Profile revisions, Workflow and parameter snapshots, scheduling plans and media variants. **No evidence these all coexist with approved data in the live DB.**
- Legacy `main.py` exposes old direct/Admin-token contracts. Most new modular routers require a composite guarded integration; old callers must not be silently given an authenticated-user role.

## Relational ERD (logical, not a live schema dump)

```text
users (id) ──< sessions(user_id)
     ├───────< jobs(owner_user_id) ──< job_attempts(job_id)
     │                                ├──< job_assets(job_id)
     │                                └──< job_input_assets(job_id)
     ├───────< input_assets(owner_user_id)
     └───────< scheduler_job_intents(owner_user_id)
                         └────────────< instance_allocations(job_id,owner_user_id)
model_families ──< model_versions ──< image_model_compatibility >── worker_images
worker_images ──< deployment_profile_revisions >── deployment_profiles
workflow_definitions ──< workflow_versions ──< workflow_compilations
scheduler_instances ──< instance_allocations ──< scheduler_usage_ledger
```

Do not infer FK/index correctness from this diagram. Real DB audits use `PRAGMA foreign_key_check`, migrations and verified row counts on a separate backup. SQLite transitional scaling requires load evidence before approving heavy multi-user concurrency or a PostgreSQL migration.

## Release capture manifest (must be filled at runtime)

| Field | Required evidence |
|---|---|
| Git SHA | Tested source and separate running container source SHA |
| Schema | Applied migration revision and checksum, pre/post record counts, owner mapping approvals |
| Worker | OCI immutable digest + signature/provenance and node/model manifest hash |
| Provider | Group/profile, readiness heartbeat, drained/idle states and actual operation IDs |
| Storage | Private bucket/object verification, representative old/new input and output SHA |
| Auth | A/B/admin/worker identities and 20 security scenarios, no raw PII in evidence |
| Operations | Backup identifier, restore duration, rollback rehearsal result |
| Release | Canary cohort, feature flags, reviewer, decision approvals, blockers and monitoring window |

## Observability and SLO policy

Track verified measurements: p50/p95 queue age, cold start/pull/model load, attempts and lease generation, Job stage timing including encoding/R2 finalization, output verification errors, asset access denies, worker heartbeat age, provider replica counts/`pending_change`, and per-currency *estimated vs invoice-derived* costs. Separate UNKNOWN/stale from healthy; do not show fake progress percentages or an exact ETA without source evidence.

**No numeric production SLO/alert thresholds are approved yet.** Establish baseline from staging and owner-reviewed cost/availability targets before public commitments. Candidate alerts: auth leakage attempt, worker unreachable, storage failure, repeated scale start, pending callback fence error, failed backup, unaudited role change, GPU runaway spending. Avoid raw prompts, filenames, tokens, signed URLs in telemetry.

## 24–48h monitoring plan (only after approved canary)

During the first 24 hours monitor authentication, A/B isolation probes, DB locks, queue persistence, actual provider starts/stops, rejected old callbacks, verified outputs and R2 access. Review at deployment and periodic intervals with an operator on-call. Expand the cohort only after no P0 errors and tracked revert point. During 24–48 hours compare real job failures, storage durability and per-currency invoice/estimate drift; do not promise any unsupported uptime or cost rate.
