# HANDOFF Phase03 -> Phase04 / Gate Resolution

**Status: PARTIAL / BLOCKED — NOT DONE_VERIFIED**. Source of latest main when built: `2738df39a17b5f93c61ada6b955a56d121dc7101`. Source code in GitHub untouched.

Offline success: owner-only list/search/history/cursor, single Job, comparison, draft, private input/output asset, download stream/ticket, upload, input permission check, cancel and hide; Worker output ownership inheritance patch; 30 Python + 3 Node tests. All resources from User A invisible to User B in these fixtures.

Priority P0 unresolved:
1. **Do not enable public signups or multi-user production**. Phase00/01/02 not DONE_VERIFIED; no approved owner mapping/real backup/restore; no verified R2/Salad runtime.
2. Implement *atomic* per-owner Job Create / idempotency scoped index / references within DB transaction **before Worker claim**; generation currently 503 on the new owner router.
3. Implement owner-scoped Retry/Regenerate including provider jobs without duplicate submit and lease fencing; retry currently 503.
4. Replace legacy admin shared-token content access with roles, metadata-only policy and audited explicit content grants; complete workflow/preset/project/session scoping.
5. Wire `frontend/src/ownerClient.js` into AuthProvider/App UI (Phase04), synchronize multi-tab events, remove token Apply and purge per-user caches; verify mobile 360px RTL and keyboard.
6. Integration regression against FULL most recent checkout, actual image/video generation, R2 real presign expiration/revoke, Cloudflare, Worker job payload input validation and isolation of GPU temporary files. No true security gate PASS before these tests.
7. Supply `GLOBAL-RULES.txt`, `DECISIONS.md`, operational `LEGACY_OWNER_PLAN` and final schema migration approval; do not assume any decision.

No production operations or destructive actions. See `TEST-REPORT.md` for coverage details and `DEPLOY-ROLLBACK.md` for staging commands only.
