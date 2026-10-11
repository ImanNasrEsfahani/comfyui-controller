# Phase 00 Test Report (evidence classification)

- **Source revision:** `bea004d97a264f892cfae6dec9c4f691aed40a39`
- **Local test host:** Python 3.13.5 / node 22.16.0 / npm 10.9.2; Ubuntu-like isolated sandbox; `pytest 9.0.2` available.
- **CI policy:** Python 3.12 / Node 22 (declared YAML), current SHA has no confirmed workflow run.
- **Test time:** generated during Phase 00, 2026-10-10 Pacific; run log in `TEST-LOG-synthetic.txt`.

| Test ID | Status | Environment | Evidence | Limitation/action |
|---|---|---|---|---|
| AT-00-01 GitHub baseline backend/worker regression | **NOT RUN** | current SHA | CI config inspected, no matching latest-run | Need checked-out repo and GitHub workflow |
| AT-00-01 frontend contract/node tests | **NOT RUN** | current SHA | `node --test tests/*.mjs` planned | Need checked-out repo |
| AT-00-01 frontend npm build | **NOT RUN** | current SHA | `npm --prefix frontend run build` planned | Need checked-out repo and dependencies |
| AT-00-01 CI for latest commit | **NOT VERIFIED** | GitHub | `actions/runs?head_sha=bea004d97a264f892cfae6dec9c4f691aed40a39` total_count=0 | Earlier-success run is not current CI |
| AT-00-02 synthetic restore | **PASS — synthetic fixture ONLY** | Python 3.13.5 SQLite | `test_sqlite_restore_exact_schema_counts_indexes_triggers`; matches schema/counts/indexes/triggers/integrity | Does NOT prove actual production-copy backup/restore |
| AT-00-02 real DB-COPY restore | **NOT RUN** | server/staging | No private DB COPY supplied | Operator must run script on authorized copy |
| AT-00-03 cross-user negative test | **GAP / NOT RUN** | current single-operator auth | no users/session/owner_user_id; shared admin token | Implement Phase 01; test A/B before multiuser release |
| SEC: read-only DB enforcement | **PASS — synthetic fixture ONLY** | Python 3.13.5 | write attempted on readonly SQLite connection rejected | Does not validate server privileges |
| R2 metadata pagination mock | **PASS — mock ONLY** | local fake client | counts prefixes across two pages; only list method invoked | No real R2 API call, actual counts unknown |
| Browser mobile 360px, RTL, keyboard | **NOT RUN** | no live UI session | Source CSS/React inspected | Capture non-sensitive screenshots on staging |
| Worker/Salad real GPU and R2 e2e | **NOT RUN** | provider not accessed | Scope exclusion and absent authorized environment | GPU job requires separate approval/budget |

**Offline commands executed:**

```bash
python -m compileall -q scripts tests
python -m unittest discover -s tests -p 'test_phase00_baseline.py' -v
```

**Overall Phase 00 exit gate:** PARTIAL/BLOCKED because live DB copy restore and latest CI/operational comparison cannot be evidenced. A synthetic restore result cannot be marketed as operational disaster recovery success.
