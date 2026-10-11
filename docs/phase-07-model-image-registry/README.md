# Phase07 — Model, Worker Image & Deployment Profile Registry

**Status: PARTIAL / BLOCKED for production**. Base GitHub main: `b54e99a2602449d55e66a72b7ba6e59390720621` (verified read-only). Exact file hashes in manifest.

Scope: opt-in, additive typed metadata registry with separate model/artifact, OCI image, GPU resources, deployment profile and immutable revision entities. User catalog is sanitized and **empty until trusted runtime compatibility and live activation**. Admin APIs require a real cookie Session, Admin role and CSRF for mutations. This project intentionally DOES NOT do real provider deploy/rollback or claim successful worker readiness without runtime tests.

User pages: `/tools`, `/models/:id`; admin pages: `/admin/models`, `/admin/worker-images`, `/admin/deployment-profiles`. The old single-operator frontend and Salad settings remain intact while default flags are OFF.

See `API-CONTRACT.md`, `TEST-REPORT.md`, `DEPLOY-ROLLBACK.md`, `RELEASE-GATE.md` and `HANDOFF.md`.
