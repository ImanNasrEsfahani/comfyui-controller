# Phase08 implementation changelog

- Added immutable, version-registered model/workflow parameter schema records (with SHA256, saved graph binding validation and explicit publish gate).
- Added LoRA metadata/version/compatibility/installation registry. No arbitrary LoRA path, URL, or download; no user-controlled installation attestation. User choices are limited to manually verified compatibility/evidence rows, and only a compatible active Worker Image/Profile.
- Added pure schema resolver for strings/text, numeric integer/number, enum, boolean, multi-select, private opaque image IDs and **decimal-string unsigned 64-bit seeds**. Unsupported parameters and constraints return field-path-specific `422`.
- Server-side CSPRNG with batch `SAME`, `INCREMENT`, `INDEPENDENT_RANDOM`; model-declared min/max bound enforcement, overflow rejection and owner-scoped immutable request-key replay. **Only an Intent is created, not a Job.**
- Added safe LoRA graph transformation for actual declared `LoraLoader` / `LoraLoaderModelOnly` nodes; unselected/disabled loaders are removed and downstream model/clip links bypassed. Enabled weights are effective in the compiled offline graph. Unsupported multi-LoRA order fails closed.
- Added owner-only personal Preset create/list/detail/rename/soft-delete/compatibility preview. Saved selections retain disabled LoRA weights; input Asset ID is not stored in Preset until retention policy approved; private prompt only with explicit opt-in, and secrets/URLs rejected.
- Added cookie/CSRF frontend client, schema-driven user control panel, LoRA cards, seed control, intent preview, private Presets page; Generate remains disabled with explicit explanation.
- Complete replacement `frontend/src/app/router.jsx`, `frontend/src/auth/routeUtils.js`, `frontend/src/layouts/Layouts.jsx` includes the Phase07 router integration that had only a local installer in prior stage. Existing `App.jsx` is preserved.
- Added exact-commit Python installer for `main.py` and worker ownership patch, and a copy-only Phase08 migration script. No destructive schema change or provider API action.

**Not implemented / not claimed:** real user Job submission, real Worker consumption of generated graph, real Retry/Regenerate and seed preservation in Job attempts/Asset metadata, dynamic per-model GPU scheduler, authenticated R2 download/multipart handling, actual Runtime evidence intake/attestation, full browser/CI tests. Do not enable public production accounts.
