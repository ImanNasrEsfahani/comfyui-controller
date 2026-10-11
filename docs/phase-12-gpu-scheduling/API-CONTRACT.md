# Stage12 scheduling API (preview only, opt-in)

All endpoints require an active Phase02 cookie Session. No worker token or browser-supplied user ID can grant access. Feature gate: `SCHEDULER_V12_UI_ENABLED=true`, default `false`. They return 503 until Phase12 offline migration is applied. Responses contain no raw Prompts, original file paths, image storage keys, R2 credentials or Salad tokens.

- `GET /api/v2/scheduling/me/queue-summary`: `{eligible:int,held:int,queue_position:null,eta_seconds:null,ready:'unknown'}`; counts only own verified, pending jobs with v12 intents.
- `GET /api/v2/scheduling/me/usage`: `{allocated_seconds_estimate:number,cost_estimates_minor:{ISO_currency:int}|null,provider_actual_minor:{ISO_currency:int}|null,invoice_status:string,note:string}`; no invoice data represented as zero without evidence. Estimates only for released, active or uncertain allocations with known rate snapshots.
- `GET /api/v2/scheduling/admin/infrastructure`: Admin/operator/superadmin only, metadata observations including `readiness:'unverified'`, `provider_operations_enabled:false`.
- `GET /api/v2/scheduling/admin/allocations`: safe allocation IDs/status/clock observations; no user private fields.
- `GET /api/v2/scheduling/admin/decisions`: local intent status; `submitted_to_provider:false`.
- `POST /api/v2/scheduling/admin/scale-intents`: Admin/operator/superadmin + CSRF. Strict JSON `{revision_id,action:'start'|'stop'|'drain'|'hold',reason_code,acknowledge_non_executing_preview:true}` returns **202 local `requested`** with `submitted_to_provider:false`. Pending exact repeat returns same ID; different in-flight action returns 409. No remote effects.

Authorization uses `security.require_active_user` and `security.require_csrf` (Origin+session CSRF header). Never pass `user_id` in request bodies. Browser `schedulerClient.mjs` is path-allowlisted, cookie-only and `Cache-Control` request `no-store`.

DB `scheduler_job_intents` is not created by a user/API. A future authorized, atomic job submission may insert one only after owner-safe `workflow_compilations` and job association. `scheduler_v12.reserve_plan` is an isolated DB planning primitive with BEGIN IMMEDIATE, **not** a dispatch or signed Claim. Approved Worker compatibility evidence for real claims must come from an independent trustworthy attestation layer.
