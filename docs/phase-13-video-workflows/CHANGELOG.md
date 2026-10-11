# CHANGELOG — Stage13

- Added bounded FFprobe-based video metadata/content checks, fixed-argument FFmpeg poster/proxy helper, SHA256/size-verified streamed R2 verifier scaffold.
- Added Phase13 copy-only migration storing immutable owner-linked original metadata and variant task lifecycle.
- Added owner/session/CSRF-gated read-only video API, video schema-driven validation and locked generation endpoint.
- Added video creation/read-only edit UI, routes and nav, owner-bound media detail player + original fallback.
- Added negative testing for fake MIME, invalid formats, cross-account assets and downloads, JWT-free cookie-only client, optimistic install SHA checks.
- No edits to existing Worker/Salad, GPU dispatch, `storage.validate_outputs`, `direct_queue.finish`, or production infrastructure.
