# Phase09 CHANGELOG

- NEW `backend/app/workflow_compiler.py`: opt-in structural typed semantic DAG validator and non-executing graph compiler; limits, no class/code/path injection, owner callback for media inputs, canonical digest and redacted preview.
- NEW `backend/app/workflow_api.py`: cookie-session+CSRF owner-scoped draft/version/validate/compile-preview and strictly gated metadata-only publication.
- NEW `backend/app/migrations/phase09.py`: additive immutable version/compilation/audit schema, owner/idempotency indexes, explicit migration only.
- NEW `backend/app/workflow_templates/*.json`: five synthetic, structurally checked template examples (not evidence of Worker compatibility).
- NEW `frontend/src/pages/workflows/*`: guided draft page, own workflow list, versions/clone/validate and non-running preview.
- REPLACED three complete Phase08 frontend files: `router.jsx`, `routeUtils.js`, `Layouts.jsx` (small additive routing/navigation changes).
- NEW `scripts/phase09_prepare_checkout.py` pinned to latest main SHA/source blobs and prebuilt frontend hash; exact local patch only for original backend main/Job Records.
- NEW `scripts/phase09_migrate_copy.py`: backup to temporary copy, migrate, integrity-check, atomic new-file output.
- NEW tests + redacted evidence; no GitHub writes, DB production changes, R2, GPU or Salad calls.
