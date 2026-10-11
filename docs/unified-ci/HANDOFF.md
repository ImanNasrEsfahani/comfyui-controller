# Handoff: after unified CI file replacement

**Status: LOCAL CI TOOLING PASS / GITHUB CI AND PRODUCTION BLOCKED until independently re-tested.**

Next operator step is applying the two audited fixture edits, committing ZIP contents plus generated test files, and reading the new unified CI reports from GitHub Actions on the exact pushed commit. Do NOT start Salad, restart Docker Compose, run migrations, or enable unverified multi-user/Worker/video functionality in production as part of this handoff.

If `scripts/ci_fixture_fixes.py --apply` refuses, STOP: do not manually weaken authentication or bypass the Git hash. Compare source and generate a new reviewed patch from the actual SHA.

If `Unified CI` fails, inspect JUnit file details, artifacts and the failing module. Do not delete failing tests, ignore exit codes, weaken owner checks, or treat intentional skips as verified behavior. If CI succeeds, review `Phase 14` static API inventory, real staging restore/permissions and Worker E2E before production promotion. Release Gate is independent and fail-closed by design.
