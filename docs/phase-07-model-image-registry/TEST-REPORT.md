# Phase07 test evidence and coverage

| ID / Coverage | Status | Evidence |
|---|---|---|
| AT-07-01: bad env type, shell key, plaintext secret rejected; digest validation | PASS (synthetic) | 14 Phase07 API HTTP tests under `tests/test_phase07_registry.py`; unit fixture only |
| AT-07-01: no proven model compatibility exposed publicly | PASS (synthetic negative) | model `ready` alone cannot appear in `/api/catalog/models` |
| AT-07-02: user denies Admin API, inactive image not made ready | PASS (synthetic negative) | B user 403, cookie+CSRF, admin A fixture |
| AT-07-02: actual verified model visibility / real publish | NOT RUN | No authentic worker signature/compatibility receipt; approval/activation returns 503 |
| AT-07-03: revisions immutable; validate doesn't change active | PASS (synthetic) | immutable SQLite trigger, revision history and `active_revision_id` null |
| AT-07-03: running-job drain, version-pinned retry, release switch | NOT RUN | provider orchestration and genuine Worker test unavailable |
| AT-07-04: GPU / ComfyUI / multi-image runtime compatibility | NOT RUN | No staging GPU, runtime/OCI signer, provider access or approved cost |
| SQLite source backup + new-copy migration, idempotency | PASS | `test_phase07_migration.py` |
| Python test suite | PASS: **33/33** in isolated synthetic fixture (14 Registry + 16 imported Phase06 Media + 3 Migration) | `evidence/PYTHON-TESTS.txt` |
| JavaScript test suite | PASS: **27/27** (Phase03–06 regression + 6 Registry Client) | `evidence/NODE-TESTS.txt` |
| JSX parser (Phase07 new + 3 patched frontend sources) | PASS (syntax only) | TypeScript parser diagnostics zero; **NOT** a Vite build |
| Full checkout installer + complete repo CI | NOT RUN | GitHub connector was read-only; CLI Git DNS unable to clone. Exact anchored source snippets and blob hashes inspected; this is not installer execution |
| Docker build, nginx refresh, real R2, Salad, 360px Playwright | NOT RUN | Requires full staging setup |

**Overall: PARTIAL / BLOCKED**. A test that only proves fail-closed does not replace runtime compatibility E2E evidence. Results are local and must not be described as certified for production.
