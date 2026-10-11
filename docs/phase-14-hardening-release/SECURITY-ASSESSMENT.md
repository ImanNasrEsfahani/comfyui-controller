# Security and privacy release assessment

**Release recommendation:** BLOCKED. The findings below are source-level or missing-proof observations, not a completed penetration test.

## P0 / critical risk items

- **API integration absent:** `main.py` at Git SHA `8a591a3e...` has 0 `include_router(...)` occurrences and still references `APP_INTERNAL_TOKEN`. New owner/auth/media/v11 APIs cannot be assumed live. A synthetic test cannot bridge this difference.
- **Unsafe generation path not replaced:** owner-safe atomic Generate/Retry/idempotency and signed service claim were intentionally disabled in Phase03/11. Legacy shared-token UI/Backend is not suitable for unreviewed public multi-user use.
- **Worker capability not verified:** `worker_v11_api.py` returns 503 for Claim. Trusting a self-reported node list or an arbitrary Docker tag is unsafe.
- **Owner mapping not approved:** legacy rows and R2 object prefix mappings remain unverified; a wrong backfill can leak old assets to a new account.
- **Independent production controls absent:** no verified Cloudflare↔Origin headers, private R2 ACL, SMTP, GPU drain/cost controller, or separate Worker credential scope on staged running system.

## Attack matrix to execute on staging

| Area | Negative case | Required result |
|---|---|---|
| Job/Asset | Authenticated B requests A's item, uses A's file for own job | 404/403, no signed URL or R2 operation |
| Cursor/Search | B supplies A's cursor or prompt search | Deny or own-only results; no metadata leak |
| Role | User queries Admin APIs, forged roles in body | 403; server identity authoritative |
| Worker | Browser cookie used for worker endpoint; worker token on Admin API | 401/403; service scope separate |
| CSRF | Cookie mutation from untrusted Origin | 403, no DB mutation |
| Session/MFA | Logout-all, revoked token, reset/recovery replay | No renewed asset tickets / no MFA bypass |
| Graph injection | Unknown node/custom class/path/URL/shell | 422 before queue, no GPU cost |
| Late Callback | Prior Attempt or wrong Lease completes after cancellation | Fenced; no wrong-owner gallery output |
| Storage | Guess storage key or expired signed download | No public access, fresh tickets only to owner |
| Frontend | Switch A → B in same tab | Abort fetches and release A's ObjectURLs/drafts/cache |
| Provider | Stop while running/finalizing/uncertain | Deny/drain and wait for provider confirmation |

## Evidence sanitization

`phase14_redact.py` covers common tokens, header values and signed URL query arguments. It is NOT complete DLP and cannot repair application logs which store secrets at source. In actual staging, inspect frontend bundle, container environment exposure, CI artifact contents, server logs and reverse proxy traces. Rotate credentials using the host provider's secret manager only after staged backward-compatible Worker cutover.

## Response to discovered cross-user leak

Disable public access and new scheduling, preserve incident evidence under restricted ACL, revoke sessions/tickets where possible, identify affected rows/objects, fix authorization at SQL and Worker boundaries, rerun AUTH-001..020, follow applicable incident-notification obligations. Do not delete audit evidence to hide the issue.
