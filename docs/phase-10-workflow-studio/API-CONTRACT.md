# Phase10 Studio API, contract and invariants

All paths are within `/api/v2/studio/`; Phase09 `WORKFLOW_COMPILER_ENABLED` and Phase10 `WORKFLOW_STUDIO_ENABLED` are required. Cookie session is resolved by server. **No browser bearer/admin token.** Mutation requires the Phase02 CSRF verifier. Admin/Superadmin; optionally `power_user` only after reviewed opt-in. System authoring requires Superadmin.

| Method / path | Behavior / success | Failure |
| --- | --- | --- |
| GET `nodes` | semantic `kind`, typed `inputs/outputs`, `runtime_verified:false` | 401,403,503 |
| GET `versions/:id/editor` | owner-authorized current draft and `{revision,graph,layout,viewport,base_checksum}` | 404,503 |
| PATCH `versions/:id/draft` | body `{revision:int,graph,layout,viewport}`, returns incremented server revision | 409 stale revision, 422 invalid graph/edge/layout, 403 CSRF |
| POST `versions/:id/validate` | `{revision:int}`; compiler `validated()` then commit graph/version/snapshot atomically | 409 conflict, 422 incomplete/invalid |
| GET `versions/:id/compile-preview` | sanitized node-kind/hash summary only, no inputs payload | 409 unvalidated/stale, 404 unauthorized |
| POST `versions/:id/publish` | explicit confirmation, delegates to Phase09 superadmin/compatibility/publish gate | 403/409/503 until signed attested runtime |
| POST `versions/:id/restore` | `{source_version_id}` creates a new **draft** with same graph hash; no original mutation | 403/404/422 |
| POST `workflows/:id/unpublish` | gated, audited pointer only (old published versions preserved) | 503 by default |

Incomplete editor graph is stored **separately** from Phase09 executable `workflow_versions.graph_json`. It may omit required connections while retaining strict node/port type/role/cycle checks. On explicit successful Validate, `workflow_versions.graph_json` becomes the authoritative complete graph. Phase09 immutable publish and historical snapshot triggers remain unchanged. External Phase09 writes to a draft change its checksum and force 409 before another Studio update.

Disabled `WORKFLOW_STUDIO_ENABLED` returns 503; disabled `VITE_WORKFLOW_STUDIO_ENABLED` uses the unchanged Phase09 pages. This API does **not** create Worker jobs, certify node inventories or support user-defined ComfyUI classes.
