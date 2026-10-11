# Phase 10 — Workflow Studio (visual, versioned, opt-in)

**Status: PARTIAL / BLOCKED FOR PRODUCTION.** Base reviewed read-only `main`: `d51a4eac487bee4f69808a9e8d49016fcafe624a` (Phase09 - development).

A visual Studio operates over *semantic* typed nodes only. Authoritative server validation is layered over Phase09 `validated()` and requires owner/superadmin permissions. Incomplete editor drafts can be saved safely with optimistic concurrency; validated/published versions retain immutable effective graph history. The Worker is never called.

## Main pages

- `/workflows/new` — Node palette, graph canvas, snapping, zoom/pan controls, minimap, inspector, port-connection and input-role binding forms, Undo/Redo, draft creation.
- `/workflows/:id/edit/:versionId` — persisted working-draft autosave with server revision, explicit save, server structural validation, safe compile summary and guarded publish.
- `/workflows/:id/versions` — version list, per-version structural diff, restore as NEW version. Old snapshots remain untouched.
- `/create/image`, `/edit/image` — existing Quick Mode unchanged; no additional unsafe GPU submit.

## Files and gates

Feature flags default OFF: `WORKFLOW_STUDIO_ENABLED`, `VITE_WORKFLOW_STUDIO_ENABLED`. Phase09 backend must also be installed and `WORKFLOW_COMPILER_ENABLED=true` only in an approved test sandbox. `WORKFLOW_STUDIO_POWER_USERS_ENABLED` requires approved role policy; otherwise only `admin` / `superadmin` roles can access Studio, while changing system workflows always requires `superadmin`.

Stage10 API: `GET /api/v2/studio/nodes`, `GET /api/v2/studio/versions/{vid}/editor`, `PATCH /api/v2/studio/versions/{vid}/draft`, `POST /api/v2/studio/versions/{vid}/validate`, `GET /api/v2/studio/versions/{vid}/compile-preview`, `POST /api/v2/studio/versions/{vid}/publish`, `POST /api/v2/studio/versions/{vid}/restore`, and `POST /api/v2/studio/workflows/{did}/unpublish` (separately OFF). Do not assume legacy `/api/workflows/` API is replaced.

The typed node catalog is derived from Phase09's semantic allowlist, **not** from attested Worker inventory; every catalog entry is `runtime_verified:false`. Model / GPU compatibility, video runtime, frontend browser experience, and successful production publish are unverified. CSS mobile fallback and keyboard connector controls exist; WCAG/browser E2E is **NOT RUN**.
