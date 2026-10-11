# TEST-REPORT — 2026-10-10 — Phase01

**Test environment:** Python 3.13.5, sqlite3 (stdlib), `argon2-cffi 25.1.0`, `unittest`/`pytest` installed. Test data are invented, NOT copied from production. Source audited from GitHub main `48b0bb50fe3cd582f37e9049a3988a83db9c4a24`.

Command: `cd <package-root> && python -m unittest discover -s tests -p test_phase01_identity.py -v`.

**Result:** 14 local tests PASS. Evidence: `evidence/TEST-LOG-unittest.txt`.

| Acceptance ID | Outcome | Test evidence | Release caveat |
|---|---|---|---|
| AT-01-01 | PASS (synthetic only) | revision double-up/idempotency, owner FK, index check, original snapshot trigger retained | Full migrated production copy NOT RUN |
| AT-01-02 | PASS (synthetic only) | 5 unclaimed historical resources flagged; A/B scoped reads fail closed; explicit legacy owner mapping does not assign orphan assets | Real mapping UNKNOWN, no human legacy approval |
| AT-01-03 | PARTIAL | `idempotency_keys` mapping permits shared key A/B independently; optional copy-only indexed jobs test permits same client ID across users, rejects duplicate inside owner | Old global unique index remains by default; no new owner-aware production public API; job_records/db.py patch on real source NOT RUN |
| AT-01-04 | NOT RUN | Legacy trigger retention tested; old code untouched; copy-only installer tested on matching fragments | Whole repo pytest, job/worker integration, frontend build, CI rerun NOT RUN in this isolated container |
| AT-01-05 | PASS (synthetic only) | online sqlite backup API, `PRAGMA integrity_check`, reversible empty-copy down and fail-closed down once users exist | Actual production DB restore drill NOT RUN |

Additional tests: session secret stored only as SHA256, wrong-account revocation rejected, suspended/pending unable to open session, hashing Argon2id, password incorrect negative, admin proof required, foreign-key invalid owner rejection, owner-scoped preset and output-asset read.

No real API-level A/B test was performed; do **not** infer endpoint authorization from DAO unit tests. No browser/GPU/Salad/R2, live DB, full code checkout or staging access in this run. No invented evidence of release readiness.

**Phase exit gate:** BLOCKED (Phase00 not DONE_VERIFIED, DECISIONS/LEGACY_OWNER_PLAN pending, real copy/restore/regression unavailable). The source CI Regression Suite for current SHA was reported `success` on GitHub; that is an observed upstream CI fact, **not** this patch's post-modification result.
