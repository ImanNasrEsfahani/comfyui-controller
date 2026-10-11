# Threat model — Phase 00

**Assets:** private prompts, images and videos (R2), Jobs, snapshots, signed URLs, users/sessions (future), Salad provider controls, Worker lease tokens and allocation records, audit metadata.

**Actors:** anonymous visitor; normal user A; normal user B; admin; Worker on Salad; backend scheduler/service; external storage or GPU service. Current runtime authenticates by one shared admin token, not distinct A/B sessions; A/B scenarios below are *future tests* and currently not demonstrable.

| ID | Threat/path | Current evidence / gap | Required mitigation and negative test | Severity |
|---|---|---|---|---|
| T01 | IDOR `GET /api/jobs/{id}`, images, download | only shared admin token; no user owner authorization | A gets 404/403 for B's IDs across each private route; query enforces owner | Critical |
| T02 | Submit references B's `input_assets`/`job_assets` | inputs lack owner_user_id | Verify every input asset and role server-side; deny B's asset to A, including replay | Critical |
| T03 | Signed R2 URL copied/replayed | presigned temporary GET URLs; URL itself is a bearer capability until expiry | short TTL, private bucket, no external referrers/logs, check owner BEFORE issuing; revoke/rotate strategy, abuse-rate cap | High |
| T04 | Shared `APP_INTERNAL_TOKEN` entered by browser | current user browser receives admin credential by design | replace with per-user secure HttpOnly session; admin service secrets never in browser | Critical |
| T05 | Session fixation/CSRF on planned cookies | no cookie-based user sessions yet | SameSite, HttpOnly, Secure, session rotation; CSRF origin/token for mutating routes; test cross-site | High |
| T06 | XSS via prompt, filenames, workflow metadata | rich React UI and mixed text | escaping/sanitization; CSP; never inject raw HTML; test malicious filenames/prompts | High |
| T07 | Client request ID collisions | unique index global on client_request_id | unique per owner; compare request hash; same key different payload -> 409 | High |
| T08 | LocalStorage drafts/presets leak between A and B on shared browser | scoped by workflow only in App.jsx | migrate to account-scoped server storage; clear/rotate cached state at logout; A/B logout/login test | High |
| T09 | Worker token exposure / impersonation | service credential separate; `X-Worker-Token` | rotate secret, TLS, env-only, worker identity/generation + least privilege, rate-limit | High |
| T10 | Lease takeover / stale callbacks / old attempt | hashed tokens and attempt fencing in direct_queue; effectiveness needs integration validation | test expired token, old generation, late complete; never mutate new attempt | High |
| T11 | Arbitrary Workflow node / dynamic input injection | admin can edit API-format graph; no user Studio yet | allowlisted typed compiler, validated schema, versioned published graph; forbid arbitrary user graph/shell | Critical |
| T12 | Cross-tenant GPU work/cache overlap | shared instance planned; scratch filesystem currently Worker controlled | isolated per-job prefixes/work dirs; allocation audit; clean ephemeral inputs; no cross-account output | Critical |
| T13 | Unscoped provider scaling cost | current user token also controls Salad | admin-only provider control; user jobs through quota/fair scheduler; hold/drain with confirmations | High |
| T14 | Unsafe storage prefix / traversal | output endpoint validates `outputs/{job_id}/`; upload uses opaque IDs | owner checks + prefix scheme; strict canonical keys; replay and traversal regression | High |
| T15 | Logs/export contain secrets or private prompts | raw worker/provider errors are sanitized in some paths | redact tokens, R2 keys, signed URLs, prompts, and credential-like text; test logs | High |
| T16 | Migration incorrectly exposes ownerless legacy rows | `jobs.owner` nullable + no users FK | quarantine unresolved legacy rows; staged backfill with proof, no NULL-is-public | Critical |

**Security gate:** Phase 00 A/B negative test cannot PASS without real identity/authorization implementation; expected gap, not permission to launch a multi-user UI. For any cross-user leak, stop public access, revoke where feasible, preserve sanitized audit and retest A/B before restore.
