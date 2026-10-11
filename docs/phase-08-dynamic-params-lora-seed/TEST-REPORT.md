# Phase08 verified local test report / limitations

**Test environment:** Python 3.13, pytest/FastAPI TestClient, SQLite ephemeral copy, synthetic A/B HTTPS Cookie sessions, synthetic registry compatibility rows. Node 22.16.0; TypeScript JS/JSX parser (syntax only). GitHub base `6afe73e12b74e7c16c94bc9b4c1d6dac7db06588`.

**After final edits (all tests re-run):**

| Command / environment | Result |
|---|---|
| `PYTHONPATH=backend pytest -q tests/test_phase08_migration.py tests/test_phase08_params.py tests/test_phase08_install.py` on isolated fixture | **40 PASS** (includes Phase07 imported test cases) |
| `node --test tests/*.mjs` on isolated fixture | **33 PASS** (Phase03–08 regressions) |
| TypeScript parse five new/replaced JS/JSX files | **5 parsed / 0 syntax errors** |
| `python -m compileall` Phase08 backend/install scripts | PASS |
| Phase01 isolated Python regression | 14 PASS |
| Phase06 isolated Python regression | 16 PASS |
| Phase07 isolated Python regression | 30 PASS |
| Phase02/03/05 standalone synthetic regressions | **BLOCKED at collection**, fixture omits complete `app.db` module |
| Full Git checkout Python suite and frontend Vite build | **NOT RUN**; no direct Git clone/npm registry access in local sandbox |
| Real Playwright Chrome, 360px/RTL/keyboard/screen reader | **NOT RUN** |
| Real Salad GPU, ComfyUI graph inference, R2, deployed Worker, live Retry/Regenerate | **NOT RUN** |

### Acceptance matrix

| ID | Status | Evidence and remaining gap |
|---|---|---|
| AT-08-01 | **PARTIAL** | Offline declared LoRA-loader DAG enabled/disabled/weight/order semantics and compatibility denials PASS; actual Worker graph dispatch/inference NOT RUN. |
| AT-08-02 | **PARTIAL** | Distinct owner-scoped immutable **parameter intents** produce CSPRNG random seeds; replay same key+payload returns same seeds and conflict returns 409. Atomic *Job creation* and Worker seed NOT RUN. |
| AT-08-03 | **PARTIAL/BLOCKED** | uint64 fixed/batch incremental bounds checked in local resolver; real Retry keeps Job effective seed / Regenerate keep-or-new / output-asset association NOT IMPLEMENTED. |
| AT-08-04 | **PARTIAL** | User API unsupported field -> 422 with `field_path`, cross-user Preset read/modify -> 404. Actual browser A/B visual tests NOT RUN. |

**Important:** Synthetic `tested_pass` compatibility rows in unit-test SQLite do NOT mean real worker signature, checksum, model inference or runtime installation has been verified. No test called R2 or Salad. All evidence logs intentionally omit private prompts, storage credentials and signed URLs.
