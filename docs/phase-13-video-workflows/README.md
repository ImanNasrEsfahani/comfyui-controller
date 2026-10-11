# Phase 13 — Video Workflows, bounded Media Pipeline

**State: PARTIAL/BLOCKED; cannot deploy to production.** Source: latest read-only GitHub `main` `a5a22d616558092e3e81504f9ed5d7061f5e0698` (Phase12 development), checked before changes and recheck required prior to packaging.

This is an actual local patch/ZIP, not a promise of working video inference. Stage11/12 are **NOT DONE_VERIFIED**. Workflow Compiler Phase09 has `UNVERIFIED_IMAGE_TO_VIDEO`/`UNVERIFIED_VIDEO_OUTPUT` and explicitly `dispatch_allowed=false`; no approved real video model/worker/image+profile pair was observed. It is unsafe to invent a compatible 32GB GPU pairing, runtime codec, actual startup bill or ETA.

Implemented:
- `backend/app/video_pipeline.py` uses real FFprobe with magic/container/codec/size/frame/duration bounds and allowlisted FFmpeg poster/proxy generation. Sample H.264 generated locally and decoded/probed. No arbitrary browser command, path or URL accepted.
- `backend/app/video_storage.py` streams private R2 object into bounded temp storage, compares HEAD and GET size, computes SHA256 and probes actual container/video metadata and decodes the whole video stream. **Standalone service primitive, not wired to old HEAD-only `direct_queue.finish`**. Must authenticate current signed lease and owner before calling.
- `backend/app/migrations/phase13.py` adds immutable original media metadata and owner-checked derivative task records. No backfill, no startup writes; offline copy script.
- `backend/app/video_api.py` is browser session + owner bound, CSRF protected for mutation, with model read-only metadata, safe parameter validate, original/derivative retrieval and a draft-only video reuse slot. Generate `/api/v2/video/jobs` explicitly 503.
- `/create/video` and `/edit/video` on the auth UI, with registered model selector, dynamic field options and honest disabled Generate. Existing `/library/:id` media detail integrates a private poster/proxy player with original download fallback. **No actual video edit model is exposed**.

Not implemented/verified: real AI video model, full ComfyUI compiling/execution, video upload API (existing upload is image-only), provider/worker R2 upload, atomically recording validated R2 Original/Poster/Proxy, long-running worker heartbeat during transcode, signed claim/allocator, billing/idempotency under real workloads, mobile browser/E2E and actual R2 streaming playback. The browser proxy adapter downloads the complete blob: **not appropriate for multi-GB video**.

The mock SQL evidence (`evidence_ref='synthetic-only'`) used in tests is a *test fixture* and does not prove any model actually runs. No GPU, Salad, R2 or production DB was accessed or changed.
