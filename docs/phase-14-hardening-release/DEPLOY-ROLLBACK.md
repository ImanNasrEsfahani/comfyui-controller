# Controlled staging / canary / rollback runbook (NOT EXECUTED)

**This is a plan, not a validated deployment or migration.** Do not execute on Production based on the ZIP alone. No GitHub write is required by this guide; the operator chooses how to review and import files.

## 0. Baseline and freeze (read-only)

1. In a disposable full checkout, verify `git rev-parse HEAD` equals `8a591a3e501ba5a09751659357c625ac05babaf0`, `git status --short` is reviewed, then inspect proposed ZIP files and hashes. A newer `main` requires rebuilding Phase14, not running an old installer.
2. Capture tested backend/frontend/Worker source SHA and deployed OCI digest separately; photograph anonymized current provider `pending_change`, desired/actual replicas and active jobs. Save encrypted DB/R2 inventory metadata in restricted storage, not CI artifacts.
3. Obtain approved, tested quiesced database copy and owner mapping. Run isolated read-only restore verification:

```bash
python3 scripts/phase14_db_drill.py \
  --source /path/to/approved-isolated.sqlite3 \
  --acknowledge-isolated-copy \
  --report ./qa/db-restore-audit.json
```

This CLI refuses a live WAL/SHM companion and never writes to the source; a local PASS is **not** proof of Production restore.

## 1. Integrate and review (NO deploy)

```bash
python3 scripts/phase14_prepare_checkout.py --repo /path/to/exact-checkout
python3 scripts/phase14_prepare_checkout.py \
  --repo /path/to/exact-checkout --export-dir /tmp/phase14-reviewed-sources
```

The export directory must not exist and must be outside the checkout. The resulting four full replacement candidates need code review, diff, AST/compiler verification, and complete tests. The installer changes **neither** GitHub nor the running system. Preserve working versions of `main.py`, `job_records.py`, `pull_worker.py` and Dockerfile. Never enable flags just because the installer succeeds.

## 2. CI and staging gates

- Run `Phase 14 - non-deploying release evidence` GitHub workflow; record run URL, artifacts, SHA, runtime versions and exact test counts. Resolve failures; **the workflow never deploys**.
- In an isolated Staging environment with distinct credentials, database, R2 bucket, SMTP sandbox, Salad project and immutable digest, test all migrations including old historical rows, approved owner backfill, `foreign_key_check`, restore timings, API contract and browser 360px/RTL/keyboard. Verify no data loss and that legacy assets still download under correct owners.
- Run all AUTH-001..020 with genuine simultaneous A/B/Admin/Worker principals and server-side ownership checks. Verify login/session/MFA policy, CSRF, error redaction and `/api/v2/worker/claim` lease isolation.
- Confirm a real model supports the tested workflow/node inventory; then with separate *cost authorization* run image Generate→R2 verified output→Preview→Download→Reuse→second Generate, request latency/progress/interrupt/restart and scale-to-zero. Video is disabled unless a separately approved model completes its own E2E.
- Rehearse rollback on Staging by stopping dispatch, draining active work, restoring the previous compatible binary/configuration and a verified backup **only when compatible**, then proving DB/R2 owner consistency. Additive migrations may require forward-fix rather than a destructive SQL downgrade. Never promise a safe rollback without rehearsing it.

## 3. Canary (only after signed P0 clearance)

Choose an owner-approved tiny cohort and a staged feature toggle plan. Maintain a ready abort path and previous signed image digest; verify provider operation confirmation before claiming Ready/Stopped. For new user-facing roles do not share legacy `APP_INTERNAL_TOKEN` and do not expose admin content by default. Record the canary start/end UTC timestamps and all measurements; expand only after independent security/QA sign-off.

## 4. Emergency procedures

- **Cross-user leak:** disable user ingress/new generation, preserve restricted evidence, revoke sessions/tickets, triage SQL owner mapping and storage prefix; rerun the full A/B matrix before resuming.
- **Runaway GPU cost:** operator Hold/Drain first, observe provider confirmation and unresolved finalization; do not assume 0 cost from a stopped UI label. Handle in-flight output R2 safely.
- **R2 outage:** stop new media work; retain Job attempts and return `NETWORK_UNKNOWN`/storage-specific status, do not fabricate success.
- **Worker crash:** fence stale leases/callbacks; drain profile, stage last approved image digest. Retry only after authorization/snapshot checks.
- **DB migration failure:** freeze scheduling; preserve pre-change snapshot; compare versions, avoid destructive rollback without an approved compatibility map. Restore on tested copy first.
- **Secret exposure:** rotate by provider-side least-privilege policy; preserve controlled incident logs without embedding credentials in GitHub.

## 5. Why this release is currently blocked

The public multi-user new API and signed Worker Claim are not wired into the current `main.py`, Phase03 ownership/Generate is incomplete, OCI runtime and video inference are unverified, approved decisions and real E2E/restore/rollback are missing. **Do not apply to Production.**
