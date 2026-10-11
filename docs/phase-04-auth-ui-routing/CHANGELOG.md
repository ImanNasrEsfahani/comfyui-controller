# Phase04 Change Log

Based on GitHub main `d5e14c83a2fde42d88c5e1d07130f06d8daab51c`.

## Existing file replaced
- `frontend/src/main.jsx`: adds opt-in `Phase04App` shell, imports phase-specific CSS. If disabled, lazy-renders the exact existing legacy App.

## New files
- `frontend/src/app/navigation.js`: safe browser History API navigation, popstate.
- `frontend/src/app/router.jsx`: route definitions, auth and role boundaries, lazy legacy fallback, page mapping.
- `frontend/src/auth/api.js`: allowlisted cookie auth API, status classification, no token persistence.
- `frontend/src/auth/routeUtils.js`: strict path / returnTo validation and role checks.
- `frontend/src/auth/session.jsx`: AuthProvider, bootstrap /session, CSRF, logout and cache invalidation, multi-tab revalidation.
- `frontend/src/auth/AuthPages.jsx`: 6 Auth routes. MFA disabled rather than fake authentication. Tokens from URL fragments cleared from history promptly.
- `frontend/src/auth/auth.css`: isolated responsive mobile-first Auth/User CSS in rtl layout.
- `frontend/src/layouts/Layouts.jsx`: Public, Auth, User, Admin, FullscreenMedia layouts and accessible links.
- `frontend/src/pages/UserPages.jsx`: Dashboard, owner-scoped Jobs/Detail/Library, security sessions, disabled Generate/Admin, placeholders for out-of-scope features.
- `frontend/.env.phase04.example`: reviewed build-time flag example (disabled).
- `tests/test_phase04_routing.mjs` and `tests/test_phase04_session_contract.mjs`: Node unit/security tests.
- `docs/phase-04-auth-ui-routing/*`: evidence, acceptance matrix, rollback/handoff.

## Untouched
No change to backend API routes, SQLite migrations, `frontend/src/App.jsx`, `frontend/src/ownerClient.js`, Vite package/dependencies, Nginx or Worker. Existing `frontend/nginx.conf` already serves SPA deep links via `try_files $uri /index.html`; production edge-proxy and CDN caching must still be validated.
