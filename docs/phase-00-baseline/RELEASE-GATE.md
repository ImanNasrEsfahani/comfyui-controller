# Phase 00 acceptance mapping

| SPEC requirement | Result | Evidence / owner |
|---|---|---|
| 01 Git SHA / CI / Compose / env.example / volume | **PARTIAL** | Report documents current repository settings; deployed settings and head CI missing |
| 02 API inventory + auth/scope | **COMPLETED (source)** | ROUTE-INVENTORY.csv, 37 endpoints with source lines |
| 03 tables / columns / migration helpers / triggers / ownerless counts | **PARTIAL** | DATABASE-INVENTORY.md source schema; live column/count inspection blocked |
| 04 actor threat model / signed URL / IDOR | **COMPLETED (design)** | THREAT-MODEL.md; negative A/B test not executable |
| 05 versioned ADR registration/DB/GPU/tenancy/Workflow/retention | **COMPLETED as OPEN proposals** | ADRS.md, all decisions await owner approval |
| 06 safe restore proof + R2 count | **PARTIAL** | mock/synthetic PASS; real DB COPY/R2 metadata NOT RUN |
| 07 feature flags/min downtime/rollback | **COMPLETED (plan only)** | FLAGS-ROLLOUT.md and DEPLOY-ROLLBACK.md; not deployed |
| DB-01 read-only SQL+count | **COMPLETED (tool)** | `scripts/phase00_db_audit.py`; no live counts |
| DB-02 SQLite WAL & staged PG risk | **COMPLETED (analysis)** | DATABASE-INVENTORY.md; benchmark NOT RUN |
| DB-03 data dictionary | **COMPLETED (source)** | DATABASE-INVENTORY.md; operational differences unknown |
| DB-04 legacy mapping | **BLOCKED** | Account owner approval / data provenance needed |
| API-01 / API-02 contract+policies | **COMPLETED (source and proposal)** | ROUTE-INVENTORY.csv |
| API-03 standard errors/contract version | **PARTIAL** | Current main.py HTTP exception maps 401/403/404/409/413/429/502/503; 422 RequestValidationError; no generic stable 500 specified; v2 pending |
| UI-01 App.jsx state/cache inventory | **COMPLETED (source)** | BASELINE-REPORT.md |
| UI-02 existing components | **PARTIAL** | one large App.jsx with upload, job/preset/ref logic; no live audit |
| UI-03 responsive screenshots | **NOT RUN** | staging/browser unavailable |
| SVC-01 compose/direct mode/worker boundary | **COMPLETED (source)** | BASELINE-REPORT.md |
| SVC-02 live image/group/R2 prefixes | **PARTIAL** | code prefix known; deployed runtime and R2 unknown |
| SVC-03 model cache/VRAM/provider | **NOT RUN** | no measured runtime |
| SEC-01 no secrets in reports | **COMPLETED (tool design)** | counts/schema only; `.env` values not exposed |
| SEC-02 threats | **COMPLETED (model)** | THREAT-MODEL.md |
| SEC-03 privacy default | **COMPLETED (design)** | ADRS.md / FLAGS-ROLLOUT.md |
| DONE-01 full baseline report | **PARTIAL** | Source inventory complete; actual DB inventory blocked |
| DONE-02 at least four ADRs with status | **PASS (document presence)** | Eight versioned OPEN ADRs with approvers |
| DONE-03 restore success or inability documented | **PASS (documentation of partial)** | Synthetic PASS; real copy explicitly NOT RUN |

**Stage conclusion:** Documentation gate partially satisfied, production readiness **BLOCKED**. This bundle is not an authorization to migrate or deploy.
