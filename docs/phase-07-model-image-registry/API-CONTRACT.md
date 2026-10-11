# Phase07 API Contract (opt-in, same-origin)

Requires `MODEL_REGISTRY_ENABLED=true`, Phase07 offline schema and an active Phase02 cookie Session. Mutations require `X-CSRF-Token` and trusted Origin. Admin role is verified from DB every request; no browser shared-token privilege.

## User (minimal DTOs)
- `GET /api/catalog/models?modality=image|video|multimodal` — only versions `ready` with actual image-compatibility `tested_pass`, provider deployment-compatibility `tested_pass`, signature `verified`, approved OCI image, ACTIVE revision pointer. Empty when evidence missing. Contains no digest, node list, secret, file path, registry origin, Worker IP, pricing guess.
- `GET /api/models/{id}` and `/api/models/{id}/capabilities` — public metadata only for eligible versions. Readiness remains `unknown` until trustworthy telemetry.

## Admin read
- `GET /api/admin/models`, `/api/admin/worker-images`, `/api/admin/gpu-profiles`, `/api/admin/deployment-profiles`, `/api/admin/deployment-variable-schema`, `/api/admin/compatibility`, `/api/admin/registry-audit`
- `GET /api/admin/deployment-profiles/{id}/history` — includes immutable revision metadata with secret-valued ENV replaced by `[configured]`.

## Admin mutation
- `POST /api/admin/models/families`, `/api/admin/models`, `/api/admin/model-artifacts`; `PATCH /api/admin/models/{id}` (`testing` or `deprecated` only).
- `POST /api/admin/worker-images`: repository in private `MODEL_REGISTRY_TRUSTED_REPOS` exact allowlist + GHCR + OCI `sha256:<64 hex>` digest. `PATCH /api/admin/worker-images/{id}` supports status `testing`/`deprecated` (cannot mutate image identity).
- `POST /api/admin/gpu-profiles`, `POST /api/admin/deployment-profiles`, `POST /api/admin/deployment-profiles/{id}/revisions` — create immutable revisions with typed, allowlisted ENV and private Vault **references** only.
- `POST /api/admin/deployment-profiles/{id}/validate?revision_id=...`: STATIC validation; returns `{static_validation:'passed', runtime_validation:'unknown', safe_to_activate:false}`. Does not call the provider.
- `POST /api/admin/deployment-profiles/{id}/{approve|activate|rollback}?revision_id=...`: **503 fail closed** until trusted CI test evidence, approved model/image inventory, rollout/drain fencing and provider rollback are implemented. No fake provider success.

IMPORTANT: Compatibility `tested_pass` and image `signature_status=verified` have NO browser API to declare them. Trusted CI/Worker attestation ingestion and independent approval are missing. Never manually set these values in production.
