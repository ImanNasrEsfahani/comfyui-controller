# Changes — unified regression CI

Source branch audited: `17427e8df417251db488dc539d522eaff443ba7b`.

- `.github/workflows/test-direct-queue.yml`: single automatic CI; correct Bash syntax; independent full test-file Python/Worker job; full frontend Node/Vite job; all-required result; artifact reporting; safe concurrency; no provider action.
- `.github/workflows/phase14-release-gate.yml`: **manual-only** release evidence and optional enforced refusal, no duplicate automatic test pipeline.
- `scripts/ci_python_matrix.py`: robust JUnit JSON reporting, isolation, zero-tests rejection, timeouts, duplicate/path validation and fail-closed suite status.
- `scripts/ci_node_report.py`: strict TAP consistency, honest skip accounting.
- `scripts/ci_fixture_fixes.py`: SHA-locked transformations of ONLY `tests/test_axis_04.py` and `tests/check_frontend_backend_upgrade.py` after user opts in locally; idempotence and content checks.
- `tests/test_ci_python_matrix.py`: updated original matrix tests and JUnit negative tests.
- `tests/test_ci_fixture_fixes.py`, `tests/test_ci_node_report.py`, `tests/test_ci_workflow_contract.py`: new validation/negative regression tests.

No production application source, direct queue, Salad worker code, `.env`, database or storage account was changed.
