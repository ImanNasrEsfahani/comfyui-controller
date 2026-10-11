# Phase 00 deliverables — reading order

1. `BASELINE-REPORT.md` — pinned GitHub SHA, CI, runtime known/unknown and source evidence.
2. `ROUTE-INVENTORY.csv`, `API-CONTRACT.md` — all current endpoints, auth scope and proposed policy.
3. `DATABASE-INVENTORY.md` — 14 **code-declared** tables, indexes, triggers and owner gaps; no live data used.
4. `THREAT-MODEL.md`, `ADRS.md` — actors/IDOR/worker/service risks and eight unapproved decisions.
5. `UI-WORKER-AUDIT.md`, `FLAGS-ROLLOUT.md` — current UI and Worker contracts, staged rollout and regression boundaries.
6. `TEST-REPORT.md`, `RELEASE-GATE.md`, `evidence/` — clearly separated synthetic passes from real-world NOT RUN.
7. `DEPLOY-ROLLBACK.md`, `R2-RUNBOOK.md`, `HANDOFF.md`, `CHANGELOG.md` — no runtime deployment made.

Additional repo-relative files: `scripts/phase00_db_audit.py`, `scripts/phase00_r2_count.py`, and `tests/test_phase00_baseline.py` are OFFLINE-only opt-in tools with isolated-copy tests. No file already present in GitHub main was modified. **Do not treat synthetic restore proof as evidence that the operational SQLite backup is recoverable.**
