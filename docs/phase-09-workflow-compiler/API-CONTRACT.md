# API Contract — v2 semantic workflows (opt-in)

All routes below are prefixed `/api/v2`; must be mounted by SHA-guarded installer and `WORKFLOW_COMPILER_ENABLED=true`. Every request requires a valid authenticated active-user cookie; all mutations require trusted Origin and `X-CSRF-Token` from `/api/auth/csrf`. API returns `Cache-Control: private, no-store`. Error status: 401 session, 403 CSRF/policy, 404 hidden owner resources, 409 state/idempotency, 422 typed field errors, 503 disabled or external gate. Preview never starts a Job.

| Method | Path | Owner / role | Behavior |
| --- | --- | --- | --- |
| GET | `/semantic-workflow-templates` | User | Five synthetic template names |
| GET | `/semantic-workflow-templates/{intent}` | User | Allowlisted semantic fixture, no runtime attestation |
| POST | `/semantic-workflows` | User (system scope: superadmin) | New private/system definition + draft v1 |
| GET | `/semantic-workflows` | User | Only owned drafts and published system metadata |
| GET | `/semantic-workflows/{id}/versions` | Owner or allowed system | Version metadata and active pointer |
| POST | `/semantic-workflows/{id}/versions` | Owner or admin | Clone latest version into immutable new identity/draft |
| GET | `/semantic-workflow-versions/{id}` | Owner or allowed system | Status/checksum, safe input schema |
| PATCH | `/semantic-workflow-versions/{id}/draft` | Owner/admin | Replace typed graph in editable draft only |
| POST | `/semantic-workflow-versions/{id}/validate` | Owner/admin | Structural validation only; no Worker |
| POST | `/semantic-workflow-versions/{id}/compile-preview` | Owner or allowed system | Verify owned Asset IDs; persist immutable private compile snapshot; return digest/count, not rendered graph |
| POST | `/semantic-workflow-versions/{id}/publish` | Superadmin + approved metadata gate | Atomic published pointer **only**, no active deployment/Job creation |

Create example request:

```json
{"title":"My image pipeline","intent":"text2img","scope":"user","model_version_id":"server-approved-model-id","graph":{"intent":"text2img","nodes":[],"edges":[],"inputs":[],"outputs":[]}}
```

The displayed empty arrays above are **shape only** and will fail validation. Use the real allowlisted JSON from `/semantic-workflow-templates/text2img` when testing.

Compile preview request:
```json
{"client_request_id":"one-click-stable-key","parameters":{"prompt":"test","negative":"none","width":1024,"height":1024,"seed":"18446744073709551615","steps":20,"cfg":3}}
```

Selected model, Workflow and schema must agree; body fields and runtime bounds are strictly checked but **not model-specific** in this phase. Successful result has `job_created=false`, `dispatch_allowed=false`, `graph_hash`, `workflow_spec_hash`, `runtime_verified=false` (unless an exact idempotent replay, which returns the same digest).

Legacy `/api/workflows`, `/api/jobs`, `JobIn v1`, and `/api/worker/*` are intentionally **untouched**. There is no `/api/v2/generation/jobs` in this module. Published historical definitions remain immutable in SQLite; preserving historical worker Retry is a separate mandatory integration test not performed.
