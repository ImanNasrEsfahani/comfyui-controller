# Phase05 — Test and acceptance report

Source SHA: `1593039f9239db6e757b633b28477aa29d6a71c2` (checked at start and near end). Host: isolated local Python 3.13 / FastAPI TestClient / SQLite synthetic Phase01 + Phase02 migration. No production data or GPU.

| Case | Status | Evidence / qualifier |
|---|---|---|
| AT-05-01 — A/B dashboard | **PASS (synthetic HTTP)** | `test_01_dashboard_sql_owner_and_aggregate_privacy`: A and B have different Job/Asset rows; count and output summary remain owner-scoped; no Job ID from the other user. |
| AT-05-02 — suspension, audit, session revoke | **PARTIAL** | `test_03_admin_suspend_revokes_and_audit_immutable`: suspended B's session and login invalidated; append-only audit rows. New Generate for users is still disabled in Phase03, so end-to-end suspension of an active GPU job was NOT RUN. |
| AT-05-03 — 403 / emails | **PASS (synthetic HTTP)** | `test_01`, `test_04`, `test_07`: normal user cannot call admin list, detail, summary or audit; changing roles requires verified superadmin and step-up password; no impersonation endpoint. |
| AT-05-04 — mobile/keyboard/back/forward | **PARTIAL / NOT RUN browser** | Responsive CSS and semantic labels, JS route tests/TS parser checks; actual 360px screenshot, screen-reader, keyboard focus and browser refresh via reverse proxy NOT RUN. |
| Migration 005 on SQLite copy | **PASS** | `test_phase05_migration.py` 2 tests: idempotent + preserves source row counts; CLI rejects lacking acknowledgement; SQLite integrity/FK checks. |
| Profile/preference/verify/data status | **PASS (synthetic HTTP)** | `test_phase05_account.py` includes preferences per user, CSRF, one-time new-email proof, old-email retention, request feature gate. Real SMTP NOT RUN. |
| Frontend Node owner/Auth regressions | **PASS, logic only** | Phase03+04+05: 13 node:test cases (10 existing, 3 added). |
| Frontend JSX parse | **PASS, syntax only** | TypeScript compiler `createSourceFile(..., ScriptKind.JSX)` parses 4 changed JSX files without syntax diagnostics. Not a Vite build. |
| Full frontend Vite build | **NOT RUN** | Full Git checkout and npm dependencies not available via this container's external network. |
| Full Python backend/worker regression | **NOT RUN** | Partial source available; `db.py` in test sandbox was an explicit local test stub and is NOT in ZIP. |
| On-host staging, Cloudflare, SMTP, Salad, R2, real backup/restore | **NOT RUN** | No authorized environment or keys available. |

Commands (offline, known results):
```
PYTHONWARNINGS=ignore PYTHONPATH=backend python -m unittest discover -s tests -p 'test_phase05_account.py' -v
# 21 PASS: 14 inherited prior Phase02 cases re-collected + 7 Phase05 cases
PYTHONPATH=backend python -m unittest discover -s tests -p 'test_phase05_migration.py' -v
# 2 PASS
node --test tests/test_phase05_frontend.mjs tests/test_phase04_routing.mjs tests/test_phase04_session_contract.mjs tests/test_phase03_owner_client.mjs
# 13 PASS
```
Total observed passes: **23 Python test executions + 13 Node tests = 36**; 14 Python executions are baseline Phase02 tests, not new Phase05 cases. Some early runs failed due to missing fake `db.py` or `active_attempt_id` test fixture; fixture updated and tests rerun. Source runtime `main.py` patcher on complete latest checkout NOT RUN. No claim of release success.

**Final Phase status: PARTIAL / BLOCKED**, not DONE_VERIFIED. Every mandatory production security gate requires staging retest and Phase03 remediation.
