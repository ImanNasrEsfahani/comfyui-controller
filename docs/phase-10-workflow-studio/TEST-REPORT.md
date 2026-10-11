# Phase10 test report (offline evidence, no production testing)

Baseline: GitHub `main` `d51a4eac487bee4f69808a9e8d49016fcafe624a`. Test runtime: CPython 3.13 / Node 22.16.0, SQLite temporary databases, FastAPI TestClient mock session and CSRF. No actual SMTP, R2, Salad, GPU or frontend browser.

Executed commands (see `evidence/`):

```sh
PYTHONPATH=. python -m pytest -q tests/test_phase10_studio.py tests/test_phase10_migration.py tests/test_phase10_install.py tests/test_phase09_compiler.py tests/test_phase09_migration.py
node --test tests/test_phase10_*.mjs
```

- **81 Python test functions PASS; 11 Python subtests PASS** (includes inherited Phase09 fixture tests and Phase09 compiler/migration regression; not 81 newly authored Phase10 tests).
- **16 JavaScript tests PASS** (pure editor transforms, guards and cookie/CSRF HTTP client).
- TypeScript JSX parser zero errors across six changed/new JS/JSX/MJS source files. `tinycss2` parser: zero CSS syntax errors.

| Acceptance | Result | Evidence and unverified portion |
| --- | --- | --- |
| AT-10-01 | PARTIAL | HTTP create/load draft, save, typed-edge deny and SQLite roundtrip PASS; drag-save-refresh **browser E2E NOT RUN** |
| AT-10-02 | PARTIAL | Pure Undo/Redo unit PASS; HTTP old-revision 409 and no silent overwrite PASS; concurrent real tabs UI **NOT RUN** |
| AT-10-03 | PARTIAL/BLOCKED | RBAC, CSRF, superadmin metadata-only publish gate, historical immutability and restore-as-new-version tested synthetically; actual approved signed Worker and publish **NOT RUN** |
| AT-10-04 | PARTIAL | Phase09 5 example structural compilation tests PASS; Quick Form actual GPU mapping, mobile 360px, RTL/keyboard screen-reader browser **NOT RUN** |

**NOT RUN:** full repository pytest suite, frontend `npm run build` (Vite/React node_modules not present), end-to-end browser/Playwright and real mobile touch/zoom, GPU/worker contract and attested inventory, R2/input references, production migrations/restore rehearsal, staged publish/unpublish and historical worker retries, full preflight against entire on-disk Git checkout. The synthetic test fixtures cannot prove production readiness.

Release status **PARTIAL / BLOCKED**: Phase09 is itself not `DONE_VERIFIED`; `GLOBAL-RULES.txt` and signed-off `DECISIONS.md` still missing. A graph passing static validation is **not** Worker-ready. If staging privacy tests fail, abort launch and keep flags off.
