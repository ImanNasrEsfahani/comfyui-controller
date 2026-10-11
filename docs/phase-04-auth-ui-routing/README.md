# Phase 04 — Auth UI, route boundary and mobile shell

**Release status: PARTIAL / BLOCKED. Do not enable public registration or multi-user production.**

Source pinned to GitHub `main` SHA `d5e14c83a2fde42d88c5e1d07130f06d8daab51c` (2026-10-11T01:15:48Z), read-only. The corresponding Phase03 HANDOFF is still `PARTIAL/BLOCKED` and does not provide Phase02/03 production DONE_VERIFIED evidence.

This ZIP carries directly replaceable repo-relative files, not an old-SHA patch script. Only the small existing `frontend/src/main.jsx` is replaced; the legacy `frontend/src/App.jsx` and its established Editor/Jobs runtime code remain unchanged. There are no backend/worker/database operations.

The new UI is opt-in **build-time**, `VITE_AUTH_UI_ENABLED=true`; default is `false`. With the flag off, original `App.jsx` runs. With the flag on, only cookie-based user views and safe informational admin views run; new user Generate/Retry are intentionally NOT enabled because Phase03 owner-safe job submission has not passed the security gate.

Implementation: lightweight History API routing (an alternative route solution, pending approval), AuthProvider, dynamic redirects and role guards, login/register/verify/forgot/reset/disabled-MFA screens, AuthLayout/PublicLayout/UserLayout/AdminLayout/FullscreenMediaLayout, active sessions page, owner-only Jobs/History/Library readers using existing Phase03 ownerClient, memory + per-tab cache invalidation, BroadcastChannel multi-tab revalidation, mobile-first RTL styling and escaped LTR prompt panel.

Not implemented: real GPU job submission; admin infrastructure mutation; owner-safe Retry/Regenerate; production SMTP/Cloudflare; MFA TOTP; full preference/preset/workflow routes and user-account policy. Existing legacy token UI is still in *unmodified legacy App.jsx* and is shown only when the Phase04 build flag is OFF, so it must not be exposed as a public multi-user frontend.

Required missing inputs: `GLOBAL-RULES.txt`, approved `DECISIONS.md`, signed `LEGACY_OWNER_PLAN`, verified previous-phase gate, backup/restore evidence, and real production SMTP integration. No implied approvals.
