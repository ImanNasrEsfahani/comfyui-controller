# Phase12 — Multi-user GPU scheduler (staging design, NOT production-ready)

Reviewed GitHub `main` at `cc9cb4d6980f7d1300afc14e93b0291e36386be8` (Phase11 development). This patch contains *only changed/new files*. All GitHub access was read-only. No Salad, R2, live DB, user account or GPU was changed.

## What is implemented

- Offline SQLite scheduler metadata: per-revision policy, owner-scoped compilation intents, provider-observation placeholders, one-live-allocation-per-job/instance, fair user turns, immutable usage records and idempotent *non-submitted* scale intents.
- Deterministic tested-image/profile/model selection; no silent model/profile fallback. SQL joins enforce verified Job owner and compiled snapshot owner, active/approved runtime metadata, and compatibility `tested_pass`.
- Shared-job plan reservations are **not** actual service dispatch, GPU allocation, Job lease or billing entries. No concurrent GPU execution; Dedicated Sessions remain disabled/unimplemented.
- Stop/drain refuses when any pending, running, finalizing, cancelled-but-unconfirmed, stalled or unknown Job exists (including legacy job modes). Provider pending-change, unknown or stale observations block stop; only a fresh stopped observation permits a *non-submitted* start intent. Idle-time policy is represented in DB but actual timed provider reconciliation is not installed.
- Cookie-session user queue and usage read endpoints; Admin/operator-only aggregate infrastructure/allocations/decisions; CSRF on Admin scale-intent drafts, and no HTTP GPU provider action. Browser sees unknown readiness and only estimates until real attestations/receipts.
- Feature flag `SCHEDULER_V12_UI_ENABLED=false` defaults off. Existing `DIRECT_GPU_AUTO_CONTROL` requires independent operator coordination and must be off in staging before exercising this patch.

## Known blockers (do not enable GPU allocation)

1. Prerequisite phases 03, 07, 11 NOT `DONE_VERIFIED` (confirmed in HANDOFF). Stage11 signed Claim intentionally 503; owner-safe accepted jobs/Retry unresolved.
2. `GLOBAL-RULES.txt` and approved `DECISIONS.md` not supplied; quota/concurrency/budget numbers are **test policy values**, not approved pricing. Operator must approve Stage12 decisions 04/05/09/15.
3. No real provider-signed instance reconcile/command issuer, multi-profile worker assigner, signed Lease issuance, allocation Release lifecycle linked to real Job callbacks, or provider invoice ingestion. Database observations can be populated only by future trusted integration; never treat self-report as readiness.
4. No proven staging GPU E2E, autoscale-zero provider confirmation, live R2 test, multiuser stress/fairness load, full frontend Vite build, mobile 360px/RTL or actual SQLite-WAL concurrency benchmark. 
5. Because `backend/app/main.py` in current GitHub still equals original legacy blob, a composite local installer is required; its resulting complete main checkout was **not** tested end to end. Correctness of earlier composite patches is NOT `DONE_VERIFIED`.

**Overall release status: PARTIAL / BLOCKED.** See `DEPLOY-ROLLBACK.md` for a review-only safe sequence.
