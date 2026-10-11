# Phase09 release gate and requirements matrix

| Requirement | Status | Evidence / reason |
| --- | --- | --- |
| Semantic typed DAG/allowlist/cycles/unknown ports | Implemented, locally tested | Python synthetic tests; no arbitrary class_type |
| Four required template families + text2video draft | Implemented as nonexecuting fixtures | `workflow_templates` + golden hashes; synthetic only |
| Owner A/B, CSRF, request-id conflict, private preview | Implemented, locally tested | FastAPI TestClient + SQLite mocks for session/R2 |
| Workflow versions, draft clone, compiled SHA, immutable metadata | Implemented, locally tested | DB triggers + HTTP tests; no production DB |
| Metadata-only publish pointer and history | PARTIAL | Local **synthetic** verified-worker rows; defaults disabled, real Worker not attested |
| Immutable historic Job/Retry, Worker-bound graph/snapshot | BLOCKED | Phase03 atomic owner job creation and Phase07/08 runtime/model/LoRA gates unresolved |
| Dynamic parameter schema/LoRA compiler bindings | PARTIAL | Phase08 standalone non-dispatching helpers not wired to this semantic graph path; reject unsupported fields |
| Full graphical Workflow Studio canvas, Graph Diff | OUT OF SCOPE | Phase10; guided forms only |
| Actual node class inventory, real ComfyUI /prompt, image/video outputs | NOT RUN | No verified GPU/Worker/staging credentials authorized |
| Full Git checkout Python regression, Vite build, Playwright 360px RTL/LTR | NOT RUN | Clone/npm install unavailable in container |
| Full production backup/restore, legacy owner migration | BLOCKED | Approved plan, isolated staging environment and authority missing |
| GLOBAL-RULES.txt, DECISIONS.md | BLOCKED | Required inputs not supplied; no assumed approval |

AT-09-01 structural golden offline PASS / E2E NOT RUN. AT-09-02 cross-user asset/unknown nodes/cycles/ports PASS locally, LoRA runtime NOT RUN. AT-09-03 private immutable compiled previews and scoped replay PASS, accepted Job/snapshot test NOT RUN. AT-09-04 legacy paths unchanged by source design, full contract and historic worker Retry NOT RUN. **Overall: PARTIAL / BLOCKED (not DONE_VERIFIED).**
