# CHANGELOG — Phase 06

**Added** `backend/app/migrations/phase06.py`: opt-in tables for variants, logical deletion and owner-validated immutable asset references. No destructive schema changes, no startup migration.

**Added** `backend/app/media_repository.py`: owner-only SQL pagination and filtering, variant lookup, soft deletion and reference checks. Fail-closed unsupported model/project filters.

**Added** `backend/app/media_api.py`: owner-only HTTP list/detail/thumbnail/preview/original download, 60-second optional presigned ticket, draft reuse and protected upload with decoded-format validation, separate EXIF-stripped thumbnail and R2 HEAD size/MIME validation. GPU create and reference binding remain blocked.

**Changed** `backend/app/owner_repository.py`: Phase03 reads now exclude Phase06 tombstoned assets, preventing residual reference/preview via the older Owner API; pre-Phase06 schema stays supported when tombstone table absent.

**Changed** `frontend/src/app/router.jsx`: replaces Phase04 placeholder library with new library/detail UI and enhanced job-details, adds reference draft uploader to create/edit placeholder. `VITE_AUTH_UI_ENABLED=false` retains old lazy legacy app unchanged.

**Added** `frontend/src/pages/library/*`, `frontend/src/components/media/*`, `frontend/src/components/uploads/*`: owner-scoped media client, responsive lazy gallery, full-screen viewer, multi-reference uploader, current job status display.

**Added** `scripts/phase06_prepare_checkout.py`, `scripts/phase06_migrate_copy.py`: SHA-pinned patch installer for `main.py`/`job_records.py`, offline-only DB migration CLI. The ZIP does NOT include replacement full `main.py` or `job_records.py` because complete sources were read through GitHub and cannot be checked out in the restricted container. All source hashes and anchors are gated by installer.

**Added** local synthetic HTTP/SQLite tests and Node tests; logs in evidence. No live GitHub writes/remote API requests to R2/Salad/production.
