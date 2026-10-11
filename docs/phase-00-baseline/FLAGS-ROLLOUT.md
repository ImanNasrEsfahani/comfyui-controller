# Feature flags, minimum downtime, safe rollback

**Phase 00 does not activate or change any flag.** These are proposed v1 names and rollout order; prefer an existing configuration mechanism and review migration before adding them.

| Proposed flag | Default | Dependency | Disable/revert criteria |
|---|---|---|---|
| `AUTH_V2_ENABLED` | false | approved ADR-0001/0007, sessions and CSRF tests | login/CSRF/auth errors |
| `OWNER_SCOPE_ENFORCED` | false in old single-user build; must be true before any multi-user access | migrated users/jobs/assets, A/B tests | any 3rd-party access leak -> take public multi-user traffic offline; don't disable isolation to recover |
| `PRIVATE_ASSET_URLS_V2` | false | owner-bound Asset registry, TTL tests | signed URLs accessible to wrong user |
| `USER_WORKFLOW_STUDIO` | false | admin allowlist compiler | graph injection / schema mismatch |
| `SHARED_GPU_POOL_V2` | false | scoped queue, allocation and billing | cross-user mix, unfair dispatch, stale lease |
| `DEDICATED_GPU_SESSIONS` | false | billing approval and provider capacity | runaway cost / unconfirmed stop |
| `ASSET_SHARING` | false | grants, revocation, per-request authorization | unauthorized share/replay |
| `POSTGRES_V2` | false | benchmark + backup migration runbook | migration mismatch or incompatible worker |

**Order:** (1) pin SHA/deployed image digest and collect sanitized server data; (2) take consistent read-only/safe backup and prove offline restore; (3) test schema migration in staging/DB copy; (4) deploy dual-compatible server APIs with old worker callbacks preserved; (5) introduce invite-only auth behind flag; (6) backfill owner and quarantine ambiguity; (7) turn on owner isolation **before** multi-user login; (8) A/B leak matrix; (9) canary small traffic and GPU quota checks; (10) widen rollout only after monitoring + release approval.

**Minimize downtime:** avoid destructive DDL; controlled request drain, Worker lease/callback buffering where supported; preserve old images/versioned model compatibility; use verified backup IDs, choose short maintenance window for final migration. **Rollback** uses last approved image digest/server SHA + prior compatible DB snapshot (not a blind down-migration), with R2 keys untouched, no retry replay until Worker event consistency confirmed.

**Rollback triggers:** schema counters drift, restore failure, unknown legacy owner leaks, Worker payload mismatch, HTTP 5xx/Auth surge, A/B access breach, unrecoverable finalizing Jobs, unexpected GPU replicas/cost, R2 output retrieval failure. For cross-user data exposure, disable public multi-user access; reverting `OWNER_SCOPE_ENFORCED` to false is NOT an acceptable mitigation.
