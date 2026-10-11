# Phase05 API contract: all use secure HttpOnly session and no browser admin/worker token

**Activation**: `ACCOUNT_UI_ENABLED=true` + Phase01/02/05 migrations, AUTH_ENABLED plus Phase02 security settings. Disabled by default. Mutations require `Origin`/`Referer` and `X-CSRF-Token` valid for the active session. Return `503` while disabled; `401` unauthenticated; `403` role/CSRF; `404` missing/hidden; `409` state; `422` validation; `429` throttling.

| Verb | Endpoint | Actor | Result / notes |
|---|---|---|---|
| GET, PATCH | `/api/users/me` | Active user | safe profile display, update display name only; never accepts owner ID |
| GET, PATCH | `/api/users/me/preferences` | Active user | account-scoped theme, locale, IANA timezone and optional model/ratio; no secrets |
| POST | `/api/users/me/email-change` | Active user + current password | 202 generic, hashed proof emailed to proposed address; original unchanged until verified |
| POST | `/api/users/me/verify-email-change` | Active user + one-time token | update email+unique normalized email, revoke other sessions |
| GET | `/api/dashboard/summary` | Active user | verified owner Job counters, recent 8, output total, quota unavailable, GPU unknown |
| GET | `/api/account/activity` | Active user | max 100 own sanitized auth-event metadata |
| GET | `/api/account/data-summary` | Active user | own requests; retention unapproved |
| POST | `/api/account/export-request`, `/api/account/delete-request` | Active user, additional flag | default `503`; with `ACCOUNT_REQUESTS_ENABLED=true`, persist pending human review, *not* export/delete |
| GET | `/api/admin/summary` | Admin/superadmin | aggregate counts, no private data, cost unknown |
| GET | `/api/admin/users` | Admin/superadmin | filtered, cursor-paginated safe profile rows |
| GET | `/api/admin/users/{id}` | Admin/superadmin | metadata, roles, session count, no prompts/assets or impersonation |
| PATCH | `/api/admin/users/{id}` | Admin/superadmin | status active/suspended, verified-email activation, prevent self-change/last Admin lockout, revoke sessions on suspension |
| POST | `/api/admin/users/{id}/role` | Superadmin only | step-up current password + 5 attempts/15min limit, role grant/revoke user/admin, revoke target sessions, fingerprinted audit |
| GET | `/api/admin/audit-logs` | Admin/superadmin | read-only filtered paging of sanitized append-only account events |

Existing `/api/auth/change-password`, `/api/auth/sessions`, `/api/auth/logout-all` from Phase02 power the Security page. Phase03 owner API powers existing Jobs/Library. Worker `/api/worker/*` unaffected; `APP_INTERNAL_TOKEN` remains legacy-only pending earlier security release gates.
