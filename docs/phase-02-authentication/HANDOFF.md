# HANDOFF Phase02 -> Phase03/04

**Status: PARTIAL / BLOCKED (Production / Release).** Audited GitHub main SHA: `3f749b52d375188e8844d68c42485db6668d928c` (Phase01 code now committed). Current repo has Phase01 identity tables as opt-in migration and shared-token legacy UI; it has NOT completed the Phase01 DONE_VERIFIED production checks.

What is implemented: isolated, disabled-by-default email/password API, hashed session cookie persistence and CSRF, invite/public/disabled registration, one-time hashed verification/reset, generic forgot responses, rate limiting, salted Argon2id from Phase01, revocation, role dependencies, SMTP TLS interface and fake email tests. Explicit Phase02 migration, source-pinned installer and tests included.

Do not treat these as completed: MFA/TOTP (AUTH_MFA_ENABLED=true deliberately fails closed), verified real email delivery, registration at scale, email provider retry/outbox durability, Phase03 user-scoped jobs/assets endpoints, Phase04 auth screens, client account-switch cache invalidation, real Production schema migration/backfill, staging runtime, full Repository CI/regressions, live worker/GPU. The **user session does not grant or override old `APP_INTERNAL_TOKEN` or `X-Worker-Token`**; Phase03 must explicitly bind authorization to every job/asset query and no old route may accidentally allow cookie-only access to all content.

Open prerequisites: `GLOBAL-RULES.txt`, `DECISIONS.md`, approved `LEGACY_OWNER_PLAN`, production database backup-and-restore, SMTP provider with verified domain and reliable delivery strategy, optional/required MFA decision, selected release flag policy. If any security test fails the release status remains BLOCKED. Package is only a reviewed patch proposal, not a running deployment.
