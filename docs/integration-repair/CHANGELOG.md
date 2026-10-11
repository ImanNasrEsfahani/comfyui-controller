# Integration repair changelog

- Restored full-history fixture checks for Stage08/09 frontend integrity without pinning today's frontend to obsolete historical digests.
- Replaced `/mnt/data` fixture dependencies in Phase12 test with immutable Git historic files.
- Added all-module Python subprocess test matrix to isolate historical import-time monkeypatches while preserving nonzero status for every failure.
- Declared pinned `typescript@5.9.3` and removed host-specific global TypeScript import fallback in Phase09 JS smoke test.
- Installed FFmpeg/FFprobe and frontend dependencies before their tests in both relevant GitHub workflows; added candidate export/syntax QA.
- Modified audited composite exporter to accept descendant commits only when four sensitive source blobs and prerequisite scripts are unchanged. Working files are never altered and outputs go to an outside new directory.
- Made costly GHCR Worker build manually authorized; routine pushes do not publish new worker images.
- Kept all dangerous Owner Generate/Retry, Worker Claim, Model Activate, Video Job and live GPU provider controls fail-closed.
- No DB schema change, no Docker Compose change and no automatic production migration in this package.
