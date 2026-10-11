# Phase04 Test Report

**Source revision:** `d5e14c83a2fde42d88c5e1d07130f06d8daab51c`.
**Environment:** container Node v22.16.0; TypeScript parser 5.8.3, Python 3.13.5. No production access. No real React/Vite dependency installation or full git checkout in the container.

## Tests actually performed
- `node --test tests/test_phase04_routing.mjs tests/test_phase04_session_contract.mjs` **10/10 PASS** on isolated local package + exact-matching original `ownerClient.js` blob SHA `c95057e31eb7d9092c9403ec96e82655e967b3ac` placed only in the test sandbox; original ownerClient excluded from deliverable.
- Node tests: all six Auth routes, safe redirects, unsafe host/URL-blocking, role-gate helper, email masking, fetch cookie-only, status redaction, CSRF cookie request, stale cross-account response cancellation, denied GPU admin routes and legacy localStorage cache clearing.
- TypeScript parser `createSourceFile` on 9 *changed/new* JS/JSX files **9/9 PASS**, plus unchanged ownerClient fixture parser PASS. This is syntax-only, not a Vite build.
- `git hash-object` for test fixture ownerClient matched GitHub blob SHA exactly.
- Source inspection: GitHub `frontend/nginx.conf` already has SPA `try_files $uri /index.html`; reverse-proxy `deploy/nginx/comfy.imannasr.com.conf` already routes `/api/` to backend. This is an **inspection**, not an actual deep-link HTTP test.

## Acceptance matrix
| Test ID | Status | Evidence | Blocker / next step |
|---|---|---|---|
| AT-04-01 | PARTIAL / Browser NOT RUN | Router unit tests PASS; no Playwright browser session | Playwright user/non-user/admin with real cookies, mobile + RTL/LTR checks |
| AT-04-02 | PARTIAL / HTTP NOT RUN | Static Nginx config inspected; route table unit PASS | Real HTTPS direct refresh `/jobs/:id`, `/account/security`, back/forward |
| AT-04-03 | PARTIAL / Browser NOT RUN | ownerClient unit tests: stale responses invalidated, localStorage cleared | Real browser two tabs, object URLs, websocket/polling, account switch and logout |
| AT-04-04 | PARTIAL / Build NOT RUN | JSX parser PASS; CSS media rules inspected | `npm run build` full Checkout; Playwright 360px responsive, keyboard/focus tests |

## Mandatory project regressions NOT RUN
Existing frontend `npm run build`/JS suite, backend `pytest`/unittest, full Vite+React runtime, Worker lease/retry, R2 presign, real SMTP, Cloudflare, staging A/B isolation, GPU generation and downloadable output have **NOT RUN**. Do not infer they pass from 10 isolated Node tests.

**Release gate:** BLOCKED. Phase02/03 are not DONE_VERIFIED; in particular new owner-safe Generate/Retry is absent, admin content policy unapproved and production owner backfill unrehearsed.
