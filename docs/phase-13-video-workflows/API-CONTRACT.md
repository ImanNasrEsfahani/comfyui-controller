# Phase13 opt-in API

Prerequisites: `VIDEO_V13_ENABLED=true`, existing `MEDIA_LIBRARY_ENABLED=true`, `OWNER_ISOLATION_ENABLED=true`, verified Phase01/06 + new Phase13 schema, cookie session, CSRF for POST; no browser Worker token.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/v2/video/models` | Only operator-registered video models with tested compatibility and pinned approved active image, yet readiness always `unverified_worker`, `generate_enabled=false`. |
| GET | `/api/v2/video/models/{id}/parameters` | Registry-specified FPS/resolution/duration/codec/slots; no server URLs, evidence reference or secrets. |
| POST | `/api/v2/video/validate` | Strict Pydantic request `model_version_id,intent,prompt,seconds,fps,width,height,seed,codec,start_frame?,end_frame?`; owner-authorized image references; returns `valid, effective (no prompt), dispatch_allowed:false,job_created:false`. Does not freeze a job or reserve GPU. |
| POST | `/api/v2/video/jobs` | Always 503 fail closed. |
| GET | `/api/v2/video/assets/{id}/original` | Owner-scoped streamed original, attachment. |
| GET | `/api/v2/video/assets/{id}/poster` | Owner-scoped only if matching verified `asset_variants` + ready transcode task. |
| GET | `/api/v2/video/assets/{id}/proxy` | Same, private MP4 proxy. |
| POST | `/api/v2/video/assets/{id}/reuse?slot=source_video` | Owner-scoped draft reference only; rejects unsupported slot; **no Job or lineage created**. |

The `/api/v2/video` endpoints are mounted only after SHA-gated local `phase13_prepare_checkout.py`. `VIDEO_V13_ENABLED` alone does not mount routes or enable worker inference. The ffmpeg helper and R2 streaming verifier are offline/service primitives: **not connected to a public upload path or live Worker success callback**.
