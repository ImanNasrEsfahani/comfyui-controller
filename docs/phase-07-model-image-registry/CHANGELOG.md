# Phase07 local patch CHANGELOG

Base SHA `b54e99a2602449d55e66a72b7ba6e59390720621`.

- Created additive `007_model_image_registry` SQLite migration with model families/versions/artifacts, OCI images, image/model compatibility, GPU profiles, deployment profiles, immutable revisions, env allowlist, deployment compatibility and append-only audit.
- Created session RBAC+CSRF secured admin CRUD/read APIs with digest and env validation, safe user catalog and unknown readiness when unverified.
- Kept provider approval, actual activation and rollback disabled, explicitly returning HTTP 503 rather than recording fake success.
- Added React account-aware views for tools/model details, admin models, worker images and profiles with typed env forms, no credentials in frontend.
- Included source-pinned local patch tool; existing main.py, job_records.py, router.jsx, routeUtils.js and Layouts.jsx are **not** full-file replacements in this ZIP.
- Included optional offline SQLite COPY migration helper, unit tests, logs and handoff. No production or GitHub writes.
