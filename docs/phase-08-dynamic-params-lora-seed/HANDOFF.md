# Phase08 handoff to Phase09 — status PARTIAL / BLOCKED

**Source HEAD:** `6afe73e12b74e7c16c94bc9b4c1d6dac7db06588`; all GitHub calls read-only. Complete replacement frontend plus additive new code included in ZIP, not deployed.

Ready for isolated regression: immutable per-model/workflow field schemas bound to saved graph hash, typed server validation and 64-bit decimal-string RNG policy, private owner-only Preset CRUD/preview, LoRA registry and compatibility gates, explicit safe bypass of disabled or unselected LoraLoader, constrained model order, owner-validated image IDs, private immutable idempotent nonexecuting Parameter Intent. The real legacy `App.jsx`, R2 bucket, Salad groups and DB remain unchanged.

**Must complete before DONE_VERIFIED or any production use:**
1. Phase03 verified per-owner transactional Job creation, global vs scoped idempotency, Retry with immutable snapshot, worker asset reuse / lease fencing, real A/B API and R2 private ACL tests; Phase03 still BLOCKED.
2. Phase07 runtime-attested OCI signature, model/LoRA artifact checksums, Worker capabilities and caching, verified ImageModel and Deployment pair, staged safe Profile activation, provider rollback; Phase07 still BLOCKED.
3. Bind output-specific seeds to actual immutable JobAttempt/Asset outputs and implement Regenerate keep/new seed and per-model uint64/integer limits with ComfyUI sampler tests; Phase09+.
4. Implement actual Graph compiler/parameter dispatch with matching Worker version and idempotent queue transaction; only a synthetic graph compile is tested now.
5. Decide `GLOBAL-RULES.txt`, `DECISIONS.md` (supported official models/LoRA, random seed domains, user Preset input-retention/DEC-06, API versioning) and approve `LEGACY_OWNER_PLAN`; docs are still missing.
6. Perform full checkout `npm run build`/pytest, responsive RTL/LTR 360px Playwright, keyboard/focus, R2, SMTP, worker and rollback rehearsal against staging. These are **NOT RUN** here.
7. Progressively support conditional/randomized non-seed parameters, saved Preset apply/cross-model diff/clone and admin verified LoRA installation event ingestion. No hidden GPU actions.

Never claim `seed/LoRA worker semantics DONE` from a passing offline Intent test. Verify every generated input and actual worker graph in independent staging before enabling user Generate. Do not push/commit any code using an AI-managed connector.
