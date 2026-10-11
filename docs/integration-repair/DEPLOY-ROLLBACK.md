# Delivery and safe verification — NOT PRODUCTION DEPLOY

**No production commands have been executed.** These instructions are for a disposable, separate checkout and offline CI checks, not for applying database migrations to the running server.

1. Review `PATCH-MANIFEST.json` and compare the current `main` commit with `1fa7375a075cd8348e939bf2de4a882998bde6c0`. If `main` has changed, re-review all touched file diffs before overwriting. The package contains only changed/new repo-relative paths.
2. Copy ZIP entries to a disposable Git checkout; do not overwrite `.env`, database volumes or Worker/cache state. Review `git diff --check` and `git diff --stat` and commit/push **only using your own approved workflow**.
3. In GitHub Actions, watch **both** `.github/workflows/test-direct-queue.yml` and `.github/workflows/phase14-release-gate.yml`; after applying the patch, all previously hidden skips should run. Both use `fetch-depth: 0` to access historical fixture commits. Check that the P14 inventory `Composite source integration dry run` AND exported syntax check succeed.
4. The Phase14 source exporter can be rehearsed locally in a FULL clean checkout (requires all prior scripts), with flags still off:

```bash
python3 scripts/phase14_prepare_checkout.py --repo .
mkdir -p ./qa
python3 scripts/phase14_release_gate.py --repo . --output ./qa/release.json
python3 scripts/phase14_api_inventory.py --repo . --output ./qa/api.json
```

5. Candidate-only export, if the previous command passes:

```bash
# Outside checkout: destination MUST NOT already exist.
python3 scripts/phase14_prepare_checkout.py --repo . \
  --export-dir /tmp/comfy-reviewed-candidates-$(git rev-parse --short HEAD)
```

The exporter creates four files in an *external review directory*. Neither `main.py` nor any Docker/Salad service is modified. Diff the exported full sources against the checkout and have a separate code/security review before use. Do not re-enable legacy unscoped endpoints merely to pass CI.

6. Before any operational service change: capture `git rev-parse HEAD`, `.env` flags and `docker compose ps`; obtain an encrypted, consistent database backup via approved SQLite backup procedure, test restore on an isolated clone, verify old Job/Asset counts and R2 ownership, and have a versioned rollback plan. None of those prerequisites is fulfilled by this ZIP.
7. If updated CI fails: **do not deploy**. Restore the previous versions of the changed repository files in your Git working tree. No schema migration is included in this package and no database rollback is required **for this package itself**. Do not change the live Docker Compose services on this basis.
8. Leave `OWNER_ISOLATION_ENABLED`, new Worker v11 dispatch, `VIDEO_V13_ENABLED`, new Scheduler provider actions and public registration disabled until independent environment-bound approval. Existing legacy workload should remain untouched; even the legacy system needs its own security review before multi-user exposure.

**Worker build policy:** changing the `build-salad-worker.yml` workflow does NOT build/push an OCI image. To build/push later, a human must explicitly dispatch the workflow and set `confirm_build_and_push=true`. This still does NOT deploy to Salad. New image OCI digest and compatibility must be validated separately.
