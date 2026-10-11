# Phase09 -> Phase10 / Execution Security Handoff

Base read-only main: `3d7e2539cec80f7087188101fd30b38f161011ec`. **PARTIAL / BLOCKED**, never promote to `DONE_VERIFIED` without actual staging worker.

Offline deliverables: typed semantic validator (DAG/ports/roles/output), five sample semantic fixtures, SQLite workflow definitions/revisions+immutable compilation snapshots/audit, per-user draft/clone/version list, strict non-executing compile preview and API responses that never expose prompt or storage keys, metadata publish gated by Superadmin+Phase07 rows and explicit flag.

**Mandatory before phase09 completion:** integrate Phase08 parameter/LoRA schemas with real pinned Worker class/node inventories, model-specific dimensions and seed policies; test valid LoRA graph effect against ComfyUI; implement Phase03 transactional owner Job creation, idempotent accepted request, owner-bound R2/Worker and immutable historic Retry using published compiled graph; verify staged worker graph hash exactly matches the persisted worker input; test real output confirmation and rollback.

Treat all current ComfyUI mappings as **unverified**. Metadata-only publish is not approval to dispatch. `GLOBAL-RULES.txt`, `DECISIONS.md`, approved publish policy, Worker attestation and legacy owner plan still absent. CI all-stage, Vite build, mobile/keyboard/browser and real E2E NOT RUN. The Phase10 graphical canvas may operate only on same constrained semantic allowlist, and must not unlock arbitrary ComfyUI nodes or Shell access.
