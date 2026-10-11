# ComfyUI Controller — Unified CI and historical fixture repair

**Status: LOCAL TOOLING VERIFIED / GITHUB FULL RUN NOT YET VERIFIED / PRODUCTION BLOCKED.**

Audited public GitHub `main` at `17427e8df417251db488dc539d522eaff443ba7b` (`review 01`). All repository interactions read-only. The previous push triggered two automatic workflows. The Phase14 evidence job already showed 47/49 Python **files** passing (two failed), and Frontend regression recorded 82 PASS/1 SKIP/0 FAIL before a malformed shell `exit` caused job failure. The concurrent run was not a safe production promotion.

## Root causes addressed in this package

1. There is **one automatic workflow**: `.github/workflows/test-direct-queue.yml` (`ComfyUI Controller - Unified CI`). It runs on applicable main pushes and pull requests. It separately checks every Python module, Node client tests, Vite build, Python/Worker syntax, and records static API and release evidence. A final `result` job requires both Python and Frontend jobs to succeed. Concurrency cancels stale runs on the same ref.
2. `.github/workflows/phase14-release-gate.yml` is **manual-only** and does not duplicate every regression on every push. Its optional `enforce_release` setting deliberately fails without verified staging evidence. It never deploys.
3. Heavy Salad Docker image build remains a separate explicitly authorized manual workflow, unchanged in this package. The retired Keep Warm job remains an inert manual no-op.
4. Fixed the **unclosed quotation mark** in both old `exit "$result` shell commands. The CI environment had erroneously reported a failed frontend job after 82 passing Node tests and 1 recorded skip despite zero test failures.
5. `scripts/ci_python_matrix.py` executes every discovered Python test file in an isolated interpreter, captures per-file JUnit totals and duration, and writes `qa/python-summary.json`. Any nonzero exit, missing/invalid JUnit, zero test count, missing test file or timeout is a FAIL. The suite is not silently filtered to passed phases.
6. `scripts/ci_node_report.py` parses Node TAP totals, distinguishes PASS/FAIL/SKIP and rejects missing or inconsistent summaries. A real skip is reported as SKIP, not silently PASS; a skip alone is not a failing regression in this policy, but must not count as production acceptance evidence.
7. `scripts/ci_fixture_fixes.py` **only patches two archived test files** to match current, correctly authenticated API behavior. The exact original Git blob IDs are checked before a single byte is changed. `--apply` is opt-in; the script never weakens application authentication, never accesses a real .env/database/provider, and refuses unexpected edits.
8. CI retains use of `ffmpeg` and `ffprobe` for true local sample-video tests, and installs the frontend's existing `typescript` dev dependency before JSX parsing. If a reviewed frontend lockfile is later committed, the unified CI automatically switches to `npm ci`; absent it, it emits a reproducibility warning.

## Important distinction: regression is not an end-to-end release gate

Per-file pytest isolation is a **regression strategy**, not proof that the app's modules work together in the actual running service. `backend/app/main.py` at this baseline still lacks the new opt-in router mounts; owner-safe Generate/Retry and Worker-v11 Claim remain intentionally 503. A successful unified CI run cannot approve multi-user, GPU, DB migration, or production deployment.

Phase14 manual evidence and `scripts/phase14_release_gate.py` remain fail-closed. Staging two-user HTTP/Worker/GPU/R2 tests and actual database backup/restore are required independently.

**How to apply**: see `DEPLOY-ROLLBACK.md`. The two historical test files are not directly included as complete replacements, because the SHA-checked fixture fixer safely reconstructs their full corrected versions from the precise version already in your checkout. No server restart is involved.
