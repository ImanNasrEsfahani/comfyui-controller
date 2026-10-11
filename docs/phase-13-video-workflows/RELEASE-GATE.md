# Release gate: BLOCKED

Must have separately approved `GLOBAL-RULES.txt`, `DECISIONS.md` (actual video model/license/codec, quota, retention and cost cap), stage11/12 DONE_VERIFIED, audited Phase03 owner-safe Submit/Retry, real Phase09 executable graph/registry/image compatibility and selected Worker version.

Stage separately with private DB, bucket, profile/Salad group and secrets. Need cost-approved live GPU E2E Text-to-Video **or** Image-to-Video → actual output → R2 verification → owner-scoped Viewer and download, real output dimensions/fps/codec/length vs immutable snapshot. Validate interrupted encoding/retry and no duplicate billing, GPU drain/finalization, cancellation and disconnected Worker fence.

Additional hard gates: run full Checkout Vite build, Python/Worker suite, browser/mobile 360px+RTL and screen reader, R2 real auth and expired ticket, actual video upload tests, ffmpeg CVE/security/size/timeout scan, provider invoice reconciliation, staging rollback. Only after all gates pass enable production; do not use current ZIP as production release.
