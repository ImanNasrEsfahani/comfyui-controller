# Approval queue — all OPEN

No `DECISIONS.md`, `GLOBAL-RULES.txt`, signed `LEGACY_OWNER_PLAN`, or full Phase00 production verification was supplied. No approval can be inferred from this package.

- **DEC-02 Database engine**: temporary SQLite migration against copy vs PostgreSQL cutover; DBA/Owner must approve staging/benchmark/rollback.
- **LEGACY_OWNER_PLAN**: verified original operator user_id, scope of jobs, linked outputs, unlinked inputs, dangling assets, evidence, approver; no guessing.
- **DEC-13 API migration contract**: current token-based `/api/jobs` compatibility and future `/api/v2` session-based route cutover require separate gate.
- **Registration & password/session lifecycle**: invite-only vs public and TTL/CSRF/email provider; defaults in this package are not product approvals.
- **Retention & GDPR/private export**: no automatic deletion or retention period selected.
- **Sharing & workflow permissions**: owner-only default, no grants enabled.

Record any future decision with `{id, status, approver, UTC date, reason, evidence}` in the owner's authoritative `DECISIONS.md`, not inside this proposed package.
