# Test report — unified CI fix proposal

**Actual state: LOCAL TOOLING TESTS PASS / COMPLETE REPOSITORY TESTS NOT RUN AFTER PATCH.**

Base commit verified read-only: `17427e8df417251db488dc539d522eaff443ba7b`.

## Direct GitHub evidence BEFORE this package

- Latest Phase14 backend-worker: **47 of 49 Python test files passed** in separate processes; failures `tests/test_axis_04.py` (4 API tests requiring missing fake SALAD_IMAGE/GROUP env during startup) and `tests/check_frontend_backend_upgrade.py` (5 legacy unauthenticated GETs; correct API now returns 401).
- Latest Unified predecessor frontend: **82 PASS / 0 FAIL / 1 SKIP**, then job failed due to malformed `exit "$result` shell command.
- Phase14 manual inventory and frontend jobs passed; backend-worker failed. The overall workflow was red. No production GPU/model verified.

## Tests executed for this ZIP in local tool container

- `python -m pytest -q tests/test_ci_python_matrix.py tests/test_ci_fixture_fixes.py tests/test_ci_node_report.py tests/test_ci_workflow_contract.py` → **23 passed**.
- JUnit runner executed an actual isolated pytest file, parsed `tests=5`, `failures=0`, `errors=0`, `skipped=0`, and emitted JSON: **PASS**.
- Node 22 executed a real sample TAP file with `tests=2`, `pass=1`, `skipped=1`; `ci_node_report.py` returned PASS with **explicitly recorded SKIP**.
- Both workflow YAML documents parsed successfully; all embedded Bash `run` blocks passed `bash -n`.
- Test fixture fixer was tested on synthetic exact-blob sources: dry-run, idempotent apply, hash mismatch refusal, auth header insertion, no unreviewed file changes. **The whole original GitHub test files have not been executed locally after applying the patch**, because a complete Git checkout could not be fetched into this isolated runtime.

## Not executed or unverified

- Full 49-file Python regression with patched fixtures, all 83 Node tests, full Vite build, assembled composite routing, full-repository shared-process pytest, two-account live HTTP/CSRF, real Worker/GPU/R2, DB staging restore, Cloudflare browser/mobile/RTL, image/video end-to-end.
- No new GitHub Actions run can occur until the user commits these files (GitHub connector is read-only).
- Frontend dependency lockfile is still not present in the audited source and needs a separate reviewed `npm install --package-lock-only` process for deterministic installs.

## Production blockers unchanged

`backend/app/main.py` lacks the new opt-in router mounts; atomic owner-scoped Generate/Retry and worker v11 signed Claim are deliberately disabled; metadata-only Workflow and video model execution have not been proven against GPU; production owner backfill and safe staged migration/restore lack independent attestation. Thus `DONE_VERIFIED` / production promotion = **BLOCKED** even if offline regression turns green.
