# Phase14 test report — local synthetic and standalone regression only

**Read-only HEAD at audit:** `8a591a3e501ba5a09751659357c625ac05babaf0`.

| Command | Local result | Meaning |
|---|---|---|
| `PYTHONPATH=<phase14_package> python -m pytest -q tests/test_phase14_*.py` | **24 PASS** | Release blocks, hash-aware export refusal, read-only backup on fake SQLite, static router mounts and log redaction |
| `PYTHONPATH=<phase13_extract>/backend pytest -q tests/test_phase13_pipeline.py` | 22 PASS | Actual local FFmpeg/FFprobe fixture on synthetic video, not AI inference |
| `node --test <phase13_extract>/tests/test_phase13_client.mjs` | **6 PASS** | Video client contract; not real browser playback |
| CI full Python/Worker suite on HEAD | **NOT RUN** | No clone of the full current repository in this execution environment |
| Node all-stage regression + Vite production build on HEAD | **NOT RUN** | Full checkout and npm install not run in this sandbox |
| Phase14 exact-source composite installer on full HEAD | **NOT RUN** | Only negative/no-op tests locally; no real checkout export |
| Staging API openapi/route import, direct HTTP A/B/Admin/Worker | **NOT RUN / BLOCKED** | Current `main.py` does not mount modular routers |
| Approved DB copy restore and ownership review | **NOT RUN** | Fake SQLite was used instead; no production data access |
| Full mobile 360px/RTL/keyboard/screen-reader | **NOT RUN** | No real browser staging |
| Worker image signing, GPU, private R2 download, provider scale/drain | **NOT RUN / BLOCKED** | No approved provider/cost/worker identity |
| Video model inference/E2E player | **NOT RUN / BLOCKED** | No approved runnable model and Worker contract |

Local tests are not counted as Production, staging, or cross-account live PASS. The new GitHub workflow must actually execute in GitHub Actions to establish CI success; workflow file creation does not do that. See `QA-EVIDENCE.md` for AT-14-01..05 statuses.

**Known tooling limitations:** Python stdlib SQL auditor checks only columns of known sensitive tables and a provided quiesced copy, not a live migration or R2 keys. Secret sanitizer is heuristic. Static route audit identifies mounts, not full auth policy. No frontend lock file at this SHA; future `npm install` is not exact dependency reproducibility. A security scan, browser and server-provider evidence remain mandatory.
