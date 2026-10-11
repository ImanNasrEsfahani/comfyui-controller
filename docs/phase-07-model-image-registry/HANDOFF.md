# Phase07 handoff

The registry/schema and UI are implemented locally as a **safe offline proposal**, not a production-ready multi-Worker platform. Phase07 `MODEL_REGISTRY_ENABLED=false` is default. User catalog will intentionally stay empty until trusted evidence + active revision exists. No GPU cost was incurred.

P0 gaps: real CI OCI signing/scanner intake, artifact checksum/cache verifier and avoid-re-download in actual Salad runtime; per-model heartbeat/compatibility verification; approval with independent review; staged deployment / drain / rollback; immutable snapshot revision recorded atomically on Job create/retry; provider policy and pricing; migration mapping for legacy Salad active/draft. Phase03 atomic Job ownership remains unresolved.

Security policy: no user-facing container digest, no plaintext secrets (only `vault://` references in DB; masked on read), no external arbitrary worker registry, no shell ENV, no user token in browser, admin role checked server-side. Registry audits are append-only against ordinary application SQL, not tamper-proof against a database operator.

Installer changes only files in a **local checkout** at exact source SHA. If main has progressed, STOP; review newer source and regenerate rather than applying blind patches. Preserve old resources, images, data, queues and .env; do not mutate production automatically.
