# Phase10 handoff → upcoming Phase11

**PARTIAL/BLOCKED**, pinned GitHub read-only `main` `d51a4eac487bee4f69808a9e8d49016fcafe624a`. Stage10 introduces only opt-in, non-dispatching visual drafts, optimistic SQL editor state, typed Port keyboard controls, structural validation, safe preview and immutable-history version copy. No production writes, GitHub commits, R2 or Salad activity.

P0 blockers: Prior Phase09 compiler emits structurally mocked ComfyUI graphs, not attested Worker payloads; Phase08 enabled LoRA/Seed not proven through Worker; Phase03 atomic owner-bound Generate/Retry still intentionally locked; Phase07 compatibility and signed image/secret vault remain unverified. `GLOBAL-RULES.txt`, `DECISIONS.md`, publish/global-sharing policy and staging restore plan still absent.

Technical caveat: GitHub `main.py` retains original legacy code at this SHA. Use `scripts/phase10_prepare_checkout.py` against exact old blob + source SHA to compose prior owner/auth/registry/parameters/workflow router mounts **in a disposable checkout**. Do not run obsolete Phase09 installer against newer `main`. The composite installer has not been executed against the entire current main checkout here; output must be audited with `git diff` and tested before any rollout. Existing `main.py` and `job_records.py` backups are created by local `--apply` only. DO NOT enable cross-user Generate/Retry until owner-safe Worker invariants pass.

One source of truth after validate/publish: Phase09 `workflow_versions`/`workflow_compilations`, with only one incomplete Stage10 editor working copy per version. External Phase09 draft edits lead to checksum conflict rather than silent overwrite. Separate node screen coordinates/viewport do not alter semantic graph hash.

Mobile canvas fallback/graph touch editing requires physical QA; Quick Forms remain independent. No claims that seed reproducibility, ComfyUI node compatibility or activation are complete.
