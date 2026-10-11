# CHANGELOG — Phase11

- Added separate HMAC-signed, attempt-fenced, image-digest pinned v11 execution contract to Backend and Worker.
- Added owner-verified R2 input mapping from immutable job input references, SHA256 checked staging, cleanup and semantic slot substitution.
- Added verified warm artifact cache and strict image/video output content validation utilities; removed no legacy endpoints.
- Added observational Worker hello service route behind `WORKER_V11_CAPABILITIES_ENABLED=false`, no new dispatch until verified allocator.
- Added Phase11 additive migration: worker observation history, independent lease journal, verified-output receipts, migration-copy script.
- Added source-pinned, local dry-run installer that composes earlier router mounts and opt-in Worker/Docker additions against exact current GitHub blob hashes; old default worker remains present.
- Added local isolation, late-callback, duplicate receipt, unsigned payload, wrong-image, owner A/B, partial-media, and corruption tests.

No runtime model was called and no GPU cost was incurred. Changes are not published on GitHub.
