# LOCAL CHECKOUT APPLICATION — not server deployment

## Prerequisites

- A complete local checkout with the original `main` files from commit `17427e8df417251db488dc539d522eaff443ba7b` or a later descendant retaining exactly the two audited test file blobs.
- Python 3.12+, Git, a trustworthy original copy of this ZIP. Do not work on the production server.
- Git worktree clean or independently backed up. Inspect changes before staging.

## Apply

```bash
cd /path/to/comfyui-controller
# Place the ZIP here, or use its absolute path.
unzip -o comfyui-unified-ci-root-fixes.zip -d .

# Guaranteed read-only first invocation:
python scripts/ci_fixture_fixes.py --repo .

# Apply the two SHA-verified historical test repairs locally:
python scripts/ci_fixture_fixes.py --repo . --apply
python scripts/ci_fixture_fixes.py --repo . --check

# Inspect before committing; stage ONLY intended files:
git diff --check
git status --short
git diff -- tests/test_axis_04.py tests/check_frontend_backend_upgrade.py

# Optional local tool smoke tests if pytest is installed:
python -m pytest -q tests/test_ci_python_matrix.py tests/test_ci_fixture_fixes.py tests/test_ci_node_report.py tests/test_ci_workflow_contract.py

# Review all changes, then commit/push yourself:
git add .github/workflows/test-direct-queue.yml .github/workflows/phase14-release-gate.yml
git add scripts/ci_python_matrix.py scripts/ci_node_report.py scripts/ci_fixture_fixes.py
git add tests/test_axis_04.py tests/check_frontend_backend_upgrade.py tests/test_ci_python_matrix.py tests/test_ci_fixture_fixes.py tests/test_ci_node_report.py tests/test_ci_workflow_contract.py
git add docs/unified-ci/ CI-UNIFIED-PATCH-MANIFEST.json
 git commit -m 'ci: unify regression, fix historical fixtures and report real coverage'
 git push origin main
```



**Important**: two repaired test files (`tests/test_axis_04.py`, `tests/check_frontend_backend_upgrade.py`) are generated on the checkout by the script. Ensure they are part of the new commit; simply extracting the ZIP without the `--apply` step will result in a deliberate CI failure.

## Verify GitHub Actions before touching the server

1. Open GitHub → Actions → **ComfyUI Controller - Unified CI** → your new commit SHA.
2. Confirm `python-and-worker`, `frontend`, and `result` all **success**. Examine `unified-python-*` and `unified-frontend-*` artifacts: counts, skips, `qa/api-mounts.json` and `qa/release-status.json`.
3. Do not count a successful offline CI run as proof of live Auth/Owner/Worker or safe migrations. Run **Phase 14 - Manual Release Evidence (NO DEPLOY)** for an independent candidate review when appropriate.
4. Only when the external P0 gates are independently satisfied should a separate staging deployment be considered.

## Local rollback

Before push: restore selected paths from the previous Git commit (`git restore -- <path>` for tracked paths), and remove only the new files introduced by this package after reviewing `git status`. Avoid `git reset --hard` or `git clean -fd` on unreviewed data.

After push: use `git revert <patch-commit>` in a reviewed checkout; do NOT delete past evidence runs. No database, Docker volume or live container requires a rollback because this package never deploys anything.
