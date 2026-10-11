# Phase 08 — Dynamic Parameters, LoRA, Seed, private Presets

**Source GitHub `main` revision:** `6afe73e12b74e7c16c94bc9b4c1d6dac7db06588` (read-only at packaging). **Release status:** `PARTIAL/BLOCKED`, not `DONE_VERIFIED`.

This package contains new Phase08 backend modules, additive/explicit SQLite migration, isolated browser pages, complete replacements of THREE audited frontend entry/router/layout files, tests, evidence and exact-source local installer. **No GitHub commit/branch/push, no production DB, no R2/Salad operation.**

Main design: a *parameter intent* is a private, idempotent, cryptographically-seeded, validated snapshot **without** creating or dispatching a Job. Actual Generate/Retry and Worker runtime verification remain blocked until Phase03/07 security and deployment gates are met. A synthetic ComfyUI DAG compiler is tested offline but is NOT evidence of a compatible running Worker.

Unapproved roles/users cannot access Admin schema/LoRA changes; account-scoped presets/intents never accept owner IDs from the browser. The legacy single-operator interface is the default when feature flags are off.

Read `API-CONTRACT.md`, `TEST-REPORT.md`, `DEPLOY-ROLLBACK.md`, `RELEASE-GATE.md`, `HANDOFF.md` before a staging trial.
