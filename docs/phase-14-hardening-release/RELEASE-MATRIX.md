# Release status matrix — phases 00–14

**Source at audit:** `8a591a3e501ba5a09751659357c625ac05babaf0` (read-only `main`). Hand-off contents were retrieved from GitHub; the separately executed offline tool used the hand-offs bundled in prior ZIPs. Historical unit results are not converted to `DONE_VERIFIED`.

| Phase | Historical local deliverables | Final release status | Outstanding mandatory evidence |
|---|---|---|---|
| 00 | Baseline, threat model, synthetic DB copy | PARTIAL/BLOCKED | Real DB/R2/provider backup and deployment manifest |
| 01 | Identity/owner schema, opt-in migration | PARTIAL/BLOCKED | Approved legacy owner backfill, production-copy restore, owner audit |
| 02 | Account sessions, CSRF, email interfaces | PARTIAL/BLOCKED | SMTP delivery, MFA decision, real auth E2E, replay/rate limits |
| 03 | Owner-scoped media/jobs read paths | PARTIAL/BLOCKED | **Atomic owner-bound Generate, idempotency, Retry and worker links** |
| 04 | Auth UI, routing, cache boundary | PARTIAL/BLOCKED | Full Vite/browser 360px/RTL and end-to-end session tests |
| 05 | User/Admin metadata UI | PARTIAL/BLOCKED | Real quota/retention, MFA, secure user lifecycle, E2E |
| 06 | Private gallery, owner media draft reuse | PARTIAL/BLOCKED | Actual Job→output→reuse→new Job lineage, R2 ACL |
| 07 | Model/Image/Profile registry | PARTIAL/BLOCKED | Signed OCI image, runtime and license/VRAM compatibility, rollout |
| 08 | Parameters, LoRA, Seed, Presets | PARTIAL/BLOCKED | Actual Worker graph LoRA/Seed effects, historical retry |
| 09 | Semantic Workflow/compiler preview | PARTIAL/BLOCKED | Executable audited ComfyUI graph, pinned tested nodes |
| 10 | Editor Canvas, draft and versioning | PARTIAL/BLOCKED | Full-checkout installer validation, browser and worker integration |
| 11 | Signed envelope, artifact cache/verification | PARTIAL/BLOCKED | **Claim returns 503**; no verified end-to-end signed allocation |
| 12 | Fair queue/planned allocations | PARTIAL/BLOCKED | Real provider reconciliation, GPU readiness, drain and scale-to-zero |
| 13 | FFmpeg video probe, poster/proxy, private API | PARTIAL/BLOCKED | Approved video model and GPU/R2/player E2E |
| 14 | Non-deploying CI, release & DB checks | PARTIAL/BLOCKED | Full CI on actual commit, restore rehearsal, signed evidence and staging E2E |

## P0 release blockers (must all be resolved before multi-user launch)

1. `main.py` has no new router mounts at reviewed SHA; source patch export not tested on complete checkout.
2. Phase03 user-scoped Generate/Retry lacks atomic job/asset/idempotency creation and worker attempt fencing.
3. Phase11 signed `/claim` fails closed with 503. Phase12 planner does not dispatch real workers or make confirmed Salad changes.
4. Model registry lacks independently signed/verified worker image and inference-valid graph/LoRA compatibility.
5. Approved original-owner mapping, real storage inventory, database migration backup/restore/rollback evidence missing.
6. GLOBAL-RULES.txt, approved DECISIONS.md, and a documented owner mapping plan missing; do not infer product/operator approvals.
7. Live A/B direct HTTP/Browser, real R2 private download, Admin/Worker permission matrix, production TLS and 360px accessibility have not been fully run.
8. Production GPU cycle from image generation to original download/reuse is unproven. No video claim unless approved real model E2E passes.

## P1/P2 and how to classify

P1 UX/Workflow/Usage/UI enhancements remain **PARTIAL**; P2 advanced video-edit, dedicated GPU and sharing remain **DISABLED/NOT RUN**, not silently marked Done. Neither lint/build nor source presence closes these gates. A release candidate, if allowed by owner after P0 remediation, must keep unverified features disabled.

## Master checklist mapping

The 45 final checklist items from Master §26 are all **UNVERIFIED FOR PRODUCTION** pending deployment-specific evidence. Some have supporting isolated implementation tests, but none should be silently upgraded to full product PASS. This is deliberately conservative: a single open P0 is sufficient to block broad public multi-user release.
