# QA evidence and acceptance cases

## Source and local environment

- Read-only `main` SHA `8a591a3e501ba5a09751659357c625ac05babaf0`, commit at 2026-10-11T22:21:42Z.
- Local tools: Python 3.13 / pytest, Node 22, FFmpeg. Python/Node tests were executed only on synthetic or extracted Phase13 files; not on a full cloned checkout.
- Evidence files: `evidence/PHASE14-PYTHON.txt`, `evidence/PHASE13-PYTHON.txt`, `evidence/PHASE13-NODE.txt`, `evidence/RELEASE-STATUS.json`, `evidence/SOURCE-AUDIT.json`.
- GitHub CI for this proposed ZIP **NOT RUN**. Any future GitHub Actions success must quote a run URL, commit SHA, UTC date, worker digest and downloaded artifacts.

| Acceptance | Status | Evidence / reason | Next action |
|---|---|---|---|
| AT-14-01 full CI, real restore and staged rollback | **NOT RUN** | New release tooling tests locally; only synthetic DB restore; no complete checkout/real DB | Run full CI, migration rehearsal on approved isolated copy, staged rollback |
| AT-14-02 two-user A/B, Admin, Worker Claim | **BLOCKED** | Earlier synthetic owner tests; Claim remains 503 and router unmounted | Wire and test on full checkout/staging, direct HTTP denials |
| AT-14-03 real GPU Generate→Download→Reuse and video if exposed | **BLOCKED** | No GPU invocation, real worker graph/R2/approved video model | Complete Phase03/07/09/11/12 gates then cost-approved GPU E2E |
| AT-14-04 100-user optional load and accessibility | **NOT RUN** | No full browser/load tools or staging; cannot assert SLA | 360px desktop/mobile keyboard/RTL, 5/20/100 tier testing |
| AT-14-05 paused browser reconnect preserving immutable Job | **NOT RUN** | No running multi-user Job to reconnect to | Actual independent browser + worker Job state transition and refresh |

## Mandatory auth/ownership matrix

AUTH-001 to AUTH-020 from the Master (two accounts, direct HTTP, image/job/preset isolation, admin RBAC, worker identity, session revocation, CSRF, XSS and unsafe URL injection) are **not fully verified on the deployed application**. Prior phase fixtures validate subsets only. Carry an independent, explicit 20-row `PASS/FAIL/NOT RUN` matrix forward; no inference from UI hiding.

## Optional video

Phase13 test creates/encodes a video with FFmpeg/FFprobe **without AI inference**. It does not satisfy the video product acceptance test. The video UI must remain non-submitting by default until the real model, license, digest, nodes and verified R2 delivery are checked.

## Evidence rules

Every future `PASS` must reference environment, tested SHA, database schema revision, UTC timestamp, actual HTTP status/result, responsible reviewer, and redacted raw artifact. No user identifiers, passwords, signed URLs, raw prompts or private storage keys in public GitHub artifacts. A missing or timed-out test is `NOT RUN`, not a success.
