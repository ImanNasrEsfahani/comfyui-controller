# Mandatory release / trust gates

Current: **BLOCKED**. Do NOT enable general multi-user access or switch Salad Image due solely to this package.

1. Phase00 baseline/DR, Phase03 per-owner atomic Generate and Retry, and Phase05 secure Admin operation need approved real staging DONE_VERIFIED evidence. Existing `GLOBAL-RULES.txt`, `DECISIONS.md`, Legacy Owner Plan unavailable; DEC-08 official models/digests/GPUs and DEC-13 API/Worker pairing unresolved.
2. Collect immutable trusted CI attestation tying OCI digest + verified signature/security scan/SBOM, runtime probe, model weights SHA, required nodes, license approval, model inference and GPU min VRAM/disk. Registry records remain `unknown` without it.
3. Build model/inference compatibility ingestion **service-to-service only**; no Admin browser toggle to assert runtime `tested_pass`.
4. Implement staged provider deployment, readiness model-level heartbeat, cost-aware approval, drain/fence old worker jobs and rollback to pinned previous digest; don't use image names/tags for allocation.
5. Validate legacy `settings_store.salad_active` and `salad_draft` against snapshot (read-only); create an approved mapping before cutover. Existing settings are deliberately untouched in Phase07.
6. Run full repo frontend build+Python tests+worker contracts, actual two-user auth/owner tests, Playwright mobile RTL, R2 privacy, staging provider smoke, backup/restore, rollback exercise.
7. A single security failure or unknown trusted evidence keeps Phase07 BLOCKED.
