# Phase08 additive API contract

All paths are under `/api`; opt in with both `MODEL_REGISTRY_ENABLED=true` and `DYNAMIC_PARAMETERS_ENABLED=true`, and Phase02 `AUTH_ENABLED=true` policy. All new browser endpoints require active HTTPS Cookie Session; all mutations verify Origin+CSRF. Successful private responses set `Cache-Control: private, no-store`.

| API | Method | Permission | Purpose |
|---|---|---|---|
| `/admin/parameter-schemas` | POST | admin + CSRF | Register immutable draft schema bound to exact saved Workflow graph |
| `/admin/parameter-schemas/{id}/publish` | POST | admin + CSRF | Static-publish schema; **does not approve Worker** |
| `/admin/loras`, `/admin/loras` | GET, POST | admin; POST CSRF | List/register LoRA metadata draft; no upload/runtime activation |
| `/models/{id}/parameter-schemas` | GET | user | Available published workflow schema references for verified model |
| `/models/{id}/parameter-schema?workflow_id=...` | GET | user | Current exact field schema/version and hash |
| `/models/{id}/loras` | GET | user | Compatible runtime-attested LoRA metadata only; no image/env paths |
| `/presets`, `/presets/{id}` | GET, POST, PATCH, DELETE | owner; mutation CSRF | Owner-only private Presets, soft-delete |
| `/presets/{id}/preview?model_version_id=&workflow_id=` | GET | owner | Compatibility and explicit diff; reject changed model/workflow/schema |
| `/parameter-intents` | POST | user + CSRF | Immutable owner-scoped **nonexecuting** validated snapshot; returns `can_submit:false` |
| `/parameter-intents/{id}` | GET | owner | Owner-only prior Intent; other user gets `404` |
| `/generation/jobs` | POST | user + CSRF | Deliberate `503`, no job persisted, no GPU action |

**Seed:** JSON decimal STRING, not JS number. `fixed` requires valid bound string. `random` requires `supports_random=true` in published schema and draws from CSPRNG after idempotency-key conflict resolution. Server stores immutable `seeds_per_output` as strings. `INCREMENT` overflow fails `422`. An Intent never establishes a durable *Job-to-output-seed* relationship: that needs Phase03/09.

**LoRA:** only an explicit registry ID/version/order/weight can be supplied; raw file paths and URLs are never accepted. Actual installed verified artifact, ImageModel and ModelDeployment compatibility must match. Unselected or disabled bound loaders are bypassed from the offline graph; arbitrary ComfyUI loader topology is rejected rather than silently given an order. The graph hash in an Intent is **not** a dispatched or successful Worker execution. Preset values never include a signed URL, arbitrary storage key, credential or access token.

**Image parameters:** only opaque image Asset ID; owner/verified/mime validated in SQL. No automatic source retention or R2 dispatch; input Asset IDs cannot be saved into Presets without a retention policy.
