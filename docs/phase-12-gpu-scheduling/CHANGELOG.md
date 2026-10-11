# CHANGELOG — Phase12

- Added additive `012_gpu_scheduler_planning` SQLite migration and new `scheduler_v12.py` fair planning engine. No legacy migrations or destructive backfill.
- Added permission-protected Stage12 scheduling API; scale intents are explicitly provider-disconnected and have idempotency and stop-safety guards.
- Added Stage12 user usage/queue and admin infrastructure preview pages; updates to existing router, route allowlist and user sidebar use exact GitHub source blobs.
- Added safe, SHA-pinned local-only composite installer and SQLite online-backup copy migrator.
- Added isolated A/B negative tests, HTTP permission/CSRF tests, copy migration checks, Node client tests and reproducible logs.
- No changes to Docker Worker, actual scheduler loop, legacy Direct Queue, live Salad groups, R2 or GPU.
