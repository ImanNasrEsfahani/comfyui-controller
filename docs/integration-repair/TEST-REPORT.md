# Integration repair — evidence report

## Baseline (GitHub Actions for commit `1fa7375a075cd8348e939bf2de4a882998bde6c0`)

- `ComfyUI Controller Regression Suite`, run [38181716188](https://github.com/ImanNasrEsfahani/comfyui-controller/actions/runs/38181716188): **FAIL**, `532 passed / 18 failed / 10 errors / 11 subtests passed`. Legacy and current tests ran together in one Python interpreter. Observed: missing ffmpeg; incorrect historical hash expectations; one `/mnt/data` fixture; shared identity/registry setup returning unexpected HTTP 503.
- `Phase 14 - non-deploying release evidence`, run [38181716215](https://github.com/ImanNasrEsfahani/comfyui-controller/actions/runs/38181716215): **FAIL**. Its inventory job ran 24 Phase14 tests successfully, then stopped at `REFUSED: RuntimeError Main SHA changed`; backend-worker showed the same Python failure pattern; frontend ran `81 PASS / 1 FAIL / 1 SKIP`, the failure `Cannot find module 'typescript'` in the Phase09 syntax smoke test. Vite build was SKIPPED following failure.
- A previous Worker build run [38163390205](https://github.com/ImanNasrEsfahani/comfyui-controller/actions/runs/38163390205) aborted in preflight before Docker image construction; no successful, attested new Worker image can be inferred.

## Local results AFTER the proposed patch

| Test | Result | Scope |
|---|---|---|
| `python3 -m pytest -q tests/test_phase14_prepare.py tests/test_ci_python_matrix.py tests/test_phase14_api_inventory.py tests/test_phase14_db_drill.py tests/test_phase14_redact.py tests/test_phase14_release_gate.py` | **30 PASS** | New and inherited Phase14 release tooling on a local fixture tree |
| `node --test tests/test_phase09_frontend.mjs` | **10 PASS** | Phase09 JS contract and JSX parsing with locally available TypeScript and restored frontend fixture files |
| YAML parse of all three modified workflows | **PASS** | Syntax parse, **not** GitHub Actions execution |
| Historical Stage08/09/10 ZIP/Git blob comparison | **PASS (data check)** | Confirmed archived sources correspond to committed files; GitHub historical-checkout tests themselves **NOT RUN** locally |
| Full Python regression matrix on the complete checkout | **NOT RUN** | Full Git repository cannot be cloned in this environment; new runner is tested only with synthetic test files |
| Phase14 composite export from full Git checkout | **NOT RUN** | Pinned Git ancestry/blob logic unit-tested only; Stage14 Actions will exercise actual transform once committed |
| GitHub Actions after applying this ZIP | **NOT RUN** | This assistant has read-only access and has not committed any files |
| Frontend Vite full production build | **NOT RUN** | Missing dependency installation for complete local repo |
| Real SQLite migration/backup/restore / two-user HTTP E2E | **NOT RUN** | No approved isolated production DB/production-adjacent staging |
| Salad GPU, actual Worker Claim, R2 output, video inference, Scale-to-Zero | **NOT RUN/BLOCKED** | P0 workflows fail-closed in current code |

## Acceptance status

- CI prerequisites and historical test harness: **PARTIAL — patch supplied, full GitHub run unverified**.
- Router candidate generation: **PARTIAL — source-pinned importer improved; full source execution not verified**.
- Secure owner-bound Generate/Retry: **BLOCKED, not implemented by this patch**.
- Signed compatible Worker dispatch: **BLOCKED, not implemented by this patch**.
- Stage14 release approval: **BLOCKED**, correctly fail-closed.

Do not count individual Python-file isolation as real browser, Worker, R2, or multi-user system integration. Any new action failure must be investigated and reported rather than skipped.
