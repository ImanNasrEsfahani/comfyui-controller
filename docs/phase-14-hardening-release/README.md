# Phase 14 — Hardening, Integration and Release Evidence

**Source read-only GitHub main:** `8a591a3e501ba5a09751659357c625ac05babaf0` (Phase 13 development, 2026-10-11T22:21:42Z). **Status: BLOCKED FOR RELEASE.** This package is a reviewed local implementation of *non-deploying QA infrastructure*, not a production approval.

## Delivered code and intended use

| File | Purpose | Side effects |
|---|---|---|
| `.github/workflows/phase14-release-gate.yml` | CI full Python/Worker, JS/Vite, static/runtime API inventory, release-status artifacts and manual blocking promotion | CI-only tests, no provider/deploy API |
| `scripts/phase14_release_gate.py` | Read previous HANDOFFs, decisions and external gate inventory. Always refuses `--enforce` without independent attestation | Reads checkout; writes JSON report if specified |
| `scripts/phase14_db_drill.py` | Require isolated quiesced SQLite copy; read-only Backup API -> private temporary restore, PK/FK/integrity/count/owner audit | Reads specified *offline copy*, deletes temporary restore |
| `scripts/phase14_api_inventory.py` | Detect absent/mounted routers; optional FastAPI OpenAPI route fingerprint in isolated runner | Imports local app only with `--runtime`; does not send requests |
| `scripts/phase14_prepare_checkout.py` | Strict Git SHA and blob guard; compose Phase03–13 legacy router/worker hooks and export complete **candidates** to new external directory | Never overwrites checkout or production |
| `scripts/phase14_redact.py` | Redact common credential/signature formats in CI evidence | Copies sanitized log; not a DLP guarantee |
| `tests/test_phase14_*.py` | Security-negative and backup/release-tool tests | Synthetic local fixtures only |

## Correct interpretation

CI success does **not** establish operator approval, production DB migration success, R2 private ACL, a valid Worker Image signature, lease/callback fencing, model inference, real GPU scale-down, live video delivery, or the absence of cross-user leaks. Release status must remain BLOCKED until these gates are independently evidenced. In particular, **no default feature flag is switched on**, no user can gain GPU/Salad access via this package, and no public sign-up expansion is authorized.

The source `backend/app/main.py` at this SHA has Git blob `f3fc84226be8704e4ae4d63b63babb84ca0ea291`, **zero `include_router(...)` calls**; presence of newer API modules in GitHub is not evidence that FastAPI loads them. `backend/app/worker_v11_api.py` still returns HTTP 503 for signed Worker `/claim`. Those are P0 release blockers until integrated and tested.

## Documentation

- `RELEASE-MATRIX.md`: 00–13 status and P0/P1/P2 gates.
- `QA-EVIDENCE.md`, `TEST-REPORT.md`: tested vs not tested; source revisions and timestamps.
- `SECURITY-ASSESSMENT.md`: risk and A/B matrix.
- `API-CONTRACT.md`: route/API fingerprint commands and limits.
- `ARCHITECTURE-OPERATIONS.md`: ERD, operational dependencies, observability.
- `DEPLOY-ROLLBACK.md`: staged operator process, canary, emergency pause, restore/rollback.
- `DECISIONS-OPEN.md`: DEC-01…15 requiring approval.
- `HANDOFF.md`: release blockers and next execution requirements.

No scripts here call GitHub push, Salad, R2 or live databases.
