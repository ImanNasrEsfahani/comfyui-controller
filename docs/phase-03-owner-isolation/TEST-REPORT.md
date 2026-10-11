# Phase 03 — TEST-REPORT (UTC / offline)

**Baseline commit:** `2738df39a17b5f93c61ada6b955a56d121dc7101`.

Environment: Python 3.13 with pytest/FastAPI/httpx/argon2/Pillow, Node 22; ephemeral SQLite created from Phase01+Phase02 migrations, HTTPS FastAPI TestClient, fake storage and local-only network. Account A/B and data are completely synthetic. Source of dependency modules in test sandbox is previously produced Phase01/02 package, not a fresh clone of full latest repository. No production data inspected.

Commands executed (sandbox-reconstructed dependencies, see logs):
```
python -m pytest -q tests/test_phase03_owner.py tests/test_phase03_patch.py --tb=short
node --test tests/test_phase03_owner_client.mjs
```

Outcome: **30 Python PASS, 3 JavaScript PASS** after correcting a test-only `db.utcnow()` stub. Earlier run 24/26 with 2 test-stub errors is retained as a correction record and is not concealed.

| Acceptance ID | Status | Evidence / limitation |
|---|---|---|
| AT-03-01: >=20 A/B cross-user scenarios | PARTIAL | 26 HTTP tests, including GET/LIST/SEARCH/COMPARE/ASSETS/PRESIGN/DOWNLOAD/DRAFT/CANCEL/HIDE/forged headers. Authenticated owner Generate/Retry intentionally return 503; cannot count as end-to-end PASS. |
| AT-03-02: direct HTTP + SQL-scope | PASS (implemented subset) | owner predicates occur inside SELECT/UPDATE; forged `X-User-Id`/role and worker header cannot spoof session. Does not certify old single-operator endpoints or staging. |
| AT-03-03: expired signed URL renew | PARTIAL | Owner checking and max 120s TTL tested with mocked signer; actual R2 expiration/replay and bucket ACL NOT RUN. |
| AT-03-04: reconnect/two tabs/account switch | PARTIAL | JavaScript request generation invalidation and client isolation tests PASS, real browser/two-tab and React App wiring NOT RUN. |
| Legacy owner-backfill Retry/Download | BLOCKED | No signed `LEGACY_OWNER_PLAN`, actual SQLite copy, R2 HEAD, staging/worker; generation/retry deliberately disabled. |
| Worker completion owner inheritance | PASS (synthetic) | SQL patch test checks forged owner ignored, unclaimed retained, pre-Phase01 schema compatibility. No real Worker callback test. |
| CI full regression / frontend build | NOT RUN | Full source checkout unavailable in this container; must run GitHub workflow after patch application. |
| Runtime security gate | BLOCKED | Phase01/02 `DONE_VERIFIED` prerequisites not established, public registration prohibited. |

## Important safety proof boundaries
No unsigned S3 links were returned to a foreign user in tested endpoints. Tests never hit real R2 or Salad; do not infer expiry semantics, object ACLs, operational owner-backfill or true multi-user readiness from synthetic evidence. Account-level authorization requires production provenance verified by owners/security.
