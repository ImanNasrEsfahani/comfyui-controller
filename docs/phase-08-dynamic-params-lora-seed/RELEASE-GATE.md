# Phase08 release gate

**Current result: `BLOCKED`, NOT `DONE_VERIFIED`.**

- [x] Additive SQLite migration tests, unchanged SQLite backup source
- [x] Unit/HTTP owner isolation for Presets and Intent
- [x] Reject invalid types/secret keys, unsupported fields, overflow and unverified LoRA
- [x] Offline LoRA node bypass and enabled weight tests
- [x] SHA-pinned local patch and frontend replacement audit
- [ ] Independent approved Phase07 runtime compatibility evidence
- [ ] Atomic session-owner-bound POST /api/jobs and Retry with immutable Worker snapshots
- [ ] Real A/B GPU Generate -> Output -> Retry/Regenerate -> Download with seed/output provenance
- [ ] Full repo pytest, Vite build, responsive browser test and security review
- [ ] Approved privacy, retention, model/LoRA licensing, migration/backfill and rollback governance
- [ ] Verified Staging -> Production release authorization

Production release remains blocked even if all local tests pass.
