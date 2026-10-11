# API contract and failure taxonomy — Phase 00

**Observed:** Current FastAPI is `app = FastAPI(..., version="1.3.0")`. The `main.py` exception handler maps HTTP 401,403,404,409,413,429,502,503 to fixed error codes and returns Pydantic 422 errors; 500 is not a guaranteed stable explicit public error code. Auth is a shared `X-Internal-Token` for non-Worker private routes. Existing Worker endpoints use `X-Worker-Token`; these must remain compatible until tested v2 Worker handshake exists.

**Proposal only, not implemented:**

- Every client-facing response includes `contract_version` (e.g. `2`) and a request tracing ID unrelated to prompt content. Do not change Worker contract without staged worker compatibility tests.
- 401 = no/invalid identity; 403 = known authenticated account lacking permission; 404 = absent or intentionally non-disclosed private object; 409 = state/version/idempotency conflict; 422 = invalid typed field with safe path; 429 = quota/rate limit with safe Retry-After; 500 = unexpected error with redacted public correlation code. 502/503 remain safe upstream/unavailable codes. Never include signed URLs, API tokens or raw input in error details.
- User identity must be server-resolved from a secure session rather than accepted from request `owner_user_id`. Every private SQL query requires owner/permission predicates; checking UI visibility or matching an R2 prefix is not authorization.
- Public endpoints: `/health`, sanitized `/api/workflows` and `/api/catalog`. User endpoints: Jobs/Asset uploads/history/download/draft/retry/cancel; admin: workflows edit/publish, provider lifecycle, instance budgets; worker: authenticated lease/heartbeat/result. Exact per-route mapping in `ROUTE-INVENTORY.csv`.
- Payload IDs: arbitrary workflow graph cannot be submitted by normal users; stable `workflow_version_id` + approved parameters only. Server enforces asset ownership and idempotency `(owner_user_id,client_request_id)`.
- Contract tests should include direct API negative requests (no browser), missing cookie/token, A tries B's ID, forged account ID header, expired URL, stale Worker generation, same-key different-payload and retry with snapshot version conflict.

**Status:** documented proposal; API v2 and new auth are OUT OF SCOPE for Phase 00.
