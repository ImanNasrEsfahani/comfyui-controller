# Phase 05 — User dashboard, account & admin metadata

Pinned latest GitHub `main` **1593039f9239db6e757b633b28477aa29d6a71c2** (Phase04 committed). GitHub read-only. This is a **staging proposal, PARTIAL / BLOCKED for production**.

Backend additions:
- `/api/dashboard/summary`: SQL-scoped verified-owner Job counts, 8 recent jobs and only available owner-bound output counts. No prompts, object keys, signed URLs, worker identifiers or per-job provider expense.
- `/api/users/me`, `/api/users/me/preferences`, `/api/users/me/email-change`, `/api/users/me/verify-email-change`: cookie-session identity, CSRF mutations, step-up password for email change, one-time hashed verification, existing sessions except current revoked on confirmed email change.
- `/api/account/activity`, `/api/account/data-summary`: owner-scoped, privacy-minimized events and requests. `/api/account/{export,delete}-request` are **disabled by default**; when enabled, only create a `pending_review` record (no actual export/deletion).
- `/api/admin/summary`, `/api/admin/users`, `/api/admin/users/{id}`, `/api/admin/users/{id}/role`, `/api/admin/audit-logs`: RBAC, summary-only counts, no content access, reason fingerprinted audit, session revocation on suspension and role change, step-up and rate-limit for role actions.

UI additions: responsive personal Dashboard, Profile/Email change, Preferences, Privacy requests, Security supplements (password change/logout all/activity), admin dashboard/users/detail/audit. Existing Phase04 auth shell, Phase03 owner client and legacy frontend retained. New routes are only reachable when `VITE_AUTH_UI_ENABLED=true`. The legacy app is the **default**.

Production gaps: prior Phases00-04 have unresolved verification gates; authenticated Generate/Retry still fail-closed, full owner-backfill not verified. Avatar image upload/crop, MFA, real data export/erasure, quotas, durable email outbox, real SMTP and real Browser/Worker/R2 tests are not included. Role elevation requires an **already verified `superadmin`**, not an automatic upgrade for `admin` users. No authorization for reading users' private images/prompts is supplied.

Missing approval inputs: `GLOBAL-RULES.txt`, `DECISIONS.md`, verified `LEGACY_OWNER_PLAN`, authoritative provider and admin access policies, production data snapshots and restore evidence. No policy is implicitly accepted.
