# Phase02 API and privacy contract

All endpoints under `/api/auth`. The main app mounts `auth.router` through a locally applied source-checked two-line change. Requests fail 503 unless `AUTH_ENABLED=true`, secure origin+CSRF secret configured, and Phase01+Phase02 tables are present. No admin header is accepted as a substitute for user session.

| Method | Path | Authentication | CSRF/Origin | Success | Failure |
|---|---|---|---|---|---|
| POST | `/register` | anonymous | Origin | 202 | 403 disabled/invite, 422 input, 429 limit, 503 config |
| POST | `/verify-email` | anonymous | Origin | 200 | 409 invalid/used/expired |
| POST | `/resend-verification` | anonymous | Origin | 202 | 429/422 |
| POST | `/login` | anonymous | Origin | 200 + Secure cookie | 401 generic, 429 |
| GET | `/me` | session | — | 200 | 401 |
| GET | `/session` | optional session | — | 200 anonymous/authenticated | 503 setup |
| GET | `/csrf` | session | — | 200 `{csrf_token}` | 401 |
| POST | `/logout` | session | Origin + CSRF | 200 | 401/403 |
| POST | `/logout-all` | session | Origin + CSRF | 200 | 401/403 |
| GET | `/sessions` | session | — | 200 | 401 |
| DELETE | `/sessions/{id}` | session/owner | Origin + CSRF | 204 | 404/403 |
| POST | `/forgot-password` | anonymous | Origin | 202 neutral | 429/422 |
| POST | `/reset-password` | anonymous | Origin | 200 | 409 used/expired |
| POST | `/change-password` | session | Origin + CSRF | 200 | 401/403/429 |

`GET /session` state: `anonymous` or `authenticated`. UI provider may additionally model `unknown`, `pending_verification`, `suspended` while API login intentionally uses a generic 401 for inactive/unverified identities. No session access to GPU admin or Worker APIs. Logout / reset / change-password revoke sessions. CSRF token changes with each new session. `__Host-comfy_session` is Secure+HttpOnly+SameSite=Lax and Path=/ with no Domain. Requests must use HTTPS and the explicitly configured same Origin.

Email verification and password reset URLs use hash fragments (`#token=`) so token is not transmitted in URL requests to the server. POST carries the single-use token and plaintext never enters DB. HTTP success may precede background SMTP delivery; real SMTP+bounce handling is operational gate. All database material, raw token, password, secret, prompt, input image and signed URLs must be excluded from logs/CI.

`AUTH_MFA_ENABLED=false`: endpoints for MFA are intentionally **not** implemented in this phase; 2FA is NOT a security claim. `require_role` applies only to future session-scoped user/admin handlers; the legacy admin and Worker checks are unchanged.
