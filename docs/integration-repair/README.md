# ComfyUI Controller — Phase 14 integration repair, round 1

**Status: LOCAL PATCH TESTED / PRODUCTION RELEASE BLOCKED.** No repository write, Salad call, R2 call, operational database access or Docker deployment was performed.

Baseline GitHub `main`: `1fa7375a075cd8348e939bf2de4a882998bde6c0` (Phase 14). The *source baseline* used to audit the composite router transform was `8a591a3e501ba5a09751659357c625ac05babaf0` (Phase 13). The source files pinned in `scripts/phase14_prepare_checkout.py` have **not been overwritten** in this patch.

## What this actually fixes

1. CI installs FFmpeg/FFprobe before video tests. A confirmed cause of ten setup errors in the latest GitHub Action was `FileNotFoundError: ffmpeg`.
2. Frontend declares `typescript@5.9.3` as a dev dependency, installs dependencies *before* testing JSX, and resolves TypeScript from the frontend package rather than a developer-specific `/opt/nvm/` path.
3. Phase08/09 tests validate their *historical committed frontend revisions* against pinned SHA256 values. They no longer incorrectly expect the Phase13 UI to have an older Phase08 or Phase09 file digest. GitHub Actions clones full history; no test is removed.
4. Phase12 installer fixture gets its archive-version UI files from immutable Git commits instead of `/mnt/data/*.zip` paths that do not exist in GitHub Actions.
5. Each Python test **file** runs in its own process to avoid `sys.modules`, environment, and SQLite monkeypatch contamination across historical test modules. All discovered `tests/test_*.py` plus `tests/check_*.py` execute; any failure returns a nonzero exit. This does **not** prove the full integrated deployment is safe.
6. Composite export checks Git ancestry **and** exact sensitive Git blobs **and** protected prerequisites, instead of rejecting any newer commit simply because Phase14 was committed. It remains dry-run by default and exports only into a new external directory. CI attempts real source export and compile checks without activation.
7. Multi-GB Worker OCI builds are no longer triggered implicitly by a normal push; they require a separately authorized manual workflow dispatch. Passing image-build tests is not permission to start a paid Salad GPU.
8. The Phase14 release gate remains **BLOCKED** regardless of local test counts, until operator-attested staging and security evidence exists.

## Evidence and limitations

See `TEST-REPORT.md`. The changed test harness passed 30 Python tests locally; the restored Phase09 JavaScript test file passed 10 local tests using a locally installed TypeScript package. Historical frontend snapshots in Phase08/09/10 release ZIPs were cross-checked against GitHub blob SHAs at their stage commits. **No new GitHub Actions run for this patch has occurred** (read-only policy), and none of the newly configured full-suite, candidate-export, Docker or Vite CI steps has yet been re-executed. Do not claim green CI from these local tests.

## Explicit P0 blockers not fixed here

- `backend/app/main.py` in the pinned GitHub commit has no `include_router(...)`; new Auth/Owner/Media/Registry/Workflow/Worker routes are not mounted in the shipped app. Candidate source export must be reviewed, applied in a separate staging checkout, imported and tested. Export **does not modify the current application**.
- `owner_api.generate()` and `.retry()` still intentionally return 503. They require atomic session-owner/asset-slot validation, idempotent job snapshots, lease-safe provider queue transactions and cross-user negative tests, not a superficial switch to the unscoped legacy submission path.
- `worker_v11_api.claim()` still intentionally returns 503 pending a trusted model/profile/image allocator, signed lease and actual Worker attestation. Do not unlock it by changing the flag alone.
- `video_api` generation remains blocked; supported model+Worker+graph and real output verification are unproven.
- Approved `GLOBAL-RULES.txt`, `DECISIONS.md`, `LEGACY_OWNER_PLAN.md`, real database migration/restore, Cloudflare/R2 private-bucket audit, authenticated two-user Staging E2E and GPU-cost authorization are absent. These are independent gates.
- `frontend/package-lock.json` still does not exist. This patch pins TypeScript alone, not every transitive dependency. Generate and review a lockfile after a controlled npm install before claiming reproducible deployment.

**Do not execute `docker compose up -d --build` or activate new feature flags based on this patch alone.**
