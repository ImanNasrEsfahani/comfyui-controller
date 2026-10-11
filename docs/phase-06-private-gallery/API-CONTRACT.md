# Phase06 media API contract (experimental)

All routes use the persisted `__Host-comfy_session` cookie and `security.require_active_user`, not client-supplied owner IDs. App must register `media_router` **before** the old Phase03 `owner_router` and legacy `/api/*` routes when both `OWNER_ISOLATION_ENABLED=true` and `MEDIA_LIBRARY_ENABLED=true`. Every operation requires Phase06 migrated SQLite schema. New HTTP responses are `Cache-Control: private, no-store` and `Referrer-Policy: no-referrer`.

| Method | Path | Contract |
|---|---|---|
| GET | `/api/assets?limit=24&type=image&cursor=...` | JSON `{items:[{asset_id,mime_type,width,height,size_bytes,created_at,kind,job_id}], next_cursor}`; filter values `image,video,input,output`, optional `after,before,status=available`. Cursor HMAC signed, scoped to session UID and filter set. Unsupported `model` and `project` return 422, never silently ignored. |
| GET | `/api/assets/:id` | Owner-only sanitized details, variants metadata, stored job input references; 404 for foreign/deleted |
| GET | `/api/assets/:id/thumbnail` | Authenticated `image/webp` private variant stream; **404 if no variant** rather than fallback to full original |
| GET | `/api/assets/:id/preview` | Authenticated original/private media stream, `no-store`; viewer uses ephemeral Blob URL revoked on close/session reset |
| GET | `/api/assets/:id/download` | Original binary authenticated stream; `Content-Disposition: attachment` and `nosniff`; no signed key returned |
| POST | `/api/assets/:id/download-ticket` | CSRF required; optional short-lived 60s R2 signed GET; valid until TTL even after logout; UI defaults to proxy path |
| POST | `/api/assets/:id/reuse?role=pose&slot=input.image_2` | CSRF required, owner-only. Returns `{asset_id,role,slot_key,source_job_id,state:'draft_only',can_submit:false}`. NEVER creates a job or consumes GPU |
| GET | `/api/assets/:id/lineage` | Recorded job input bindings under owner only; incomplete until job creation gate enabled |
| DELETE | `/api/assets/:id` | CSRF required, logical tombstone only; 409 if referenced by a recorded `job_input_assets` binding; job source unchanged; no R2 deletion |
| POST | `/api/uploads` | Multipart `file`; CSRF required; actual PNG/JPEG/WEBP/GIF verification, size/pixel cap, separate private thumbnail, R2 HEAD size/MIME check, then atomic owner DB row; no presigned input URL returned |
| POST | `/api/jobs/:id/references` | Explicit 503 until Phase03 owner-atomic Job creation/lineage integration; cross-user job id hidden with 404 |

No `POST /uploads/init` or `/uploads/complete` multipart session APIs introduced because direct upload is supported for the current bounded image workflow. Pause/resume large video uploads is out of scope. Note `use-as-input` legacy Phase03 route remains as a permission-only acknowledgement and does not create a job.

**Storage guarantees:** New original upload key `inputs/<opaque UUID>/original.ext`; thumbnail `thumbnails/<opaque UUID>/512.webp`, private R2 bucket. No embedded user email/name/filename. The original is not modified. `HEAD` validation failure does not expose DB rows, though private orphan blobs require offline GC review. No public ACL or browser access is granted by these routes.
