# Versioned Architecture Decision Records — Phase 00

All entries are **Proposed / OPEN**, explicitly awaiting product owner approval; no preexisting `DECISIONS.md` was supplied. No decision below authorizes production operations.

## ADR-0001 v1 — Registration policy
**Status:** OPEN — Product Owner. **Proposal:** invite-only initially (abuse/quota/email not live yet). **Options:** public sign-up vs invite-only. **Trade-off:** growth vs GPU abuse and spam risk. **Release criterion:** verified email, recover/reset, anti-abuse/limits and account ownership API tests.

## ADR-0002 v1 — DB engine and migrations
**Status:** OPEN — Product Owner + Backend/DevOps. **Proposal:** temporary SQLite for isolated staging; staged PostgreSQL target when concurrency benchmark shows need; versioned migrations (Alembic or equivalent) instead of scattered startup DDL. **Evidence required:** representative DB copy, WAL load/recovery metrics, migration dry-run, rollback rehearsal, queuing while schema changes. **No engine migration in Phase 00.**

## ADR-0003 v1 — GPU allocation and billing
**Status:** OPEN — Product Owner + DevOps/Finance. **Proposal:** shared GPU pool by default, explicit per-Job allocation/lease and fair queue; dedicated reservations behind separate flag and budget. **Constraints:** model/workflow/worker compatibility; no cross-user file reuse; distinguish provider actual vs estimated cost; admin-only Start/Stop.

## ADR-0004 v1 — Tenancy and resource ownership
**Status:** OPEN — Product Owner + Security. **Proposal:** single account owner per Job and Asset (`owner_user_id` NOT NULL) at v1; organization/team tenancy deferred but design can add tenant dimension. Private-by-default, no implicit NULL shares. Legacy mapping to **verified** original operator; unresolved rows quarantined. Per-owner idempotency & SQL predicates mandatory.

## ADR-0005 v1 — Workflow Studio edit scope
**Status:** OPEN — Product Owner + Security. **Proposal:** regular users can run only approved published parameterized workflows; Studio edit/publish restricted to admin/power-user after validated typed compiler and allowlisted nodes; never accept arbitrary ComfyUI JSON from normal users.

## ADR-0006 v1 — Retention, deletion and sharing
**Status:** OPEN — Product Owner + Privacy/Legal. **Proposal:** input/output/thumbnail retention periods and grace period to be defined separately; soft delete then safe reference-aware garbage collection; asset sharing feature OFF until validated grants. No fabricated retention day counts. No deletion scheduled.

## ADR-0007 v1 — Identity/Worker and API cutover
**Status:** OPEN — Security + Backend + DevOps. **Proposal:** HttpOnly Secure session with CSRF protection; preserve separate Worker service token, enforce lease generation; dual-stack old API for Worker through compatibility period. v2 user endpoints owner scoped; no admin/provider token sent to browser. Rotation, old endpoint retirement and contract version are migration gates.

## ADR-0008 v1 — Quotas and transactional email
**Status:** OPEN — Product Owner + Finance + Operations. **Proposal:** explicitly budget per-user concurrency/storage/GPU-seconds; select transactional email provider plus SPF/DKIM/DMARC, bounce/rate-limit/retry policies. Values and provider cannot be selected without budget/operations inputs.

## Decision log rule
Treat all ADRs as `OPEN` until an authorized human records `{decision_id, status, approver, UTC date, reasoning, follow-up evidence}` in `DECISIONS.md`. Suggestions are not approved decisions. If owner is not reachable, BLOCKED is correct.
