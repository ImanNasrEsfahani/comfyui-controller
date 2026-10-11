# Phase05 handoff to Phase06 and release/security gates

Source SHA: `1593039f9239db6e757b633b28477aa29d6a71c2`. Status **PARTIAL / BLOCKED**.

Confirmed locally: opt-in, additive Phase05 schema; account+admin HTTP endpoints and reactive routed pages; 7 Phase05 API TestClient cases and 2 migration tests; 14 Phase02 re-run test cases; 13 Node cases (Phase03/04 regression + Phase05), TypeScript JSX parsing. No GitHub write.

Highest-priority unresolved requirements:
1. `GLOBAL-RULES.txt`, `DECISIONS.md`, verified `LEGACY_OWNER_PLAN`, real production deployment SHA/SQLite backup & restore and staging owner counts have not been provided. No release approval assumed.
2. Phase03 atomic per-owner Generate/Retry/idempotency, worker claims/references, R2 input/output ACL, re-auditing all legacy admin content endpoints — prerequisite to public accounts. Continue fail-closed.
3. Full checkout Vite build, all Python/Worker regressions, 360px RTL/LTR browser with keyboard/screen-reader, Nginx Refresh, SMTP sender/verified domain & outbox durability, private R2 and Salad/GPU tests are NOT RUN.
4. Avatar crop/upload is not provided: avatar_asset_id in profile is shown only when it refers to an existing verified owner asset. No cross-user icon or presign.
5. MFA enrollment, verified account deletion/export processing, data retention period, quota figures and quota editing remain disabled/unapproved (no fake success or invented zero limits).
6. Admin content access is metadata-only. Role elevation only from an independently verified `superadmin`, with password recheck and rate limit, in audited mutation. Bootstrap CLI Phase01 creates `admin`, not `superadmin`; out-of-band role policy and approval needed.
7. Audit is append-only against ordinary application SQL update/delete; database administrators still technically control the file. The reason is stored as a fingerprint, not plain-text user text. Enterprise integrity/retention requires separate immutable storage/chain and reviewed retention policy.
8. Phase05 identity schema is opt-in. The installer changes only `main.py` on an exact SHA checkout; it does not run schema migration automatically, change Worker, or deploy.

No secrets in ZIP. Production, GitHub, R2 and provider were untouched.
