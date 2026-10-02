# Salad single-group deployment — .env is authoritative

All configurable values (group/queue names, priority, GPU, resource amounts,
worker image, scaling, health probes, API settings and credentials) are read
from the **root private `.env`**. Do not put real credentials in GitHub.

The example configuration defines:

- Queue: `qwen-comfyui-medium`
- Container group: `qwen-comfyui-5090-medium` (new name avoids the deleted group's reservation)
- Priority: `medium`; RTX 5090 (32 GB VRAM); 4 vCPU; 30 GB RAM; 2 GB SHM; 100 GB disk
- Initial/min/max replicas: `0/0/1`, queue-triggered scale-to-zero.

These are **example `.env` values**, not constants inside the deployer or backend.
Change only the root `.env` to rename/configure the group. A changed group name
creates a different Salad resource; it does NOT automatically delete the previous one.

## Apply on GitHub FIRST

1. Extract the replacement ZIP over a full checkout of `comfyui-controller`.
2. Run `python3 scripts/apply-env-source.py` once. This modifies
   `frontend/src/App.jsx` and `backend/app/db.py`. Commit those two generated
   changes alongside the replacement files.
3. Review `git diff` and `git status`; commit and push to GitHub. Never commit `.env`.

## Update the server AFTER GitHub

1. `cd /var/www/comfyui-controller && git pull`
2. Run `python3 scripts/sync-env.py`: it backs up `.env` outside the repo
   and appends missing keys from `.env.example`, preserving existing values.
3. Review the private `.env`, preserving `SALAD_API_KEY`, `R2_*` secrets and
   tokens. It is essential
   to set the new exact-name variables `SALAD_QUEUE_NAME`,
   `SALAD_CONTAINER_GROUP_NAME`, `SALAD_PRIORITY`, `SALAD_GPU_NAME`, resource
   sizes, API settings, probe options etc. Remove obsolete variables such as
   `SALAD_QUEUE_PREFIX`, `SALAD_CONTAINER_GROUP_PREFIX`, `SALAD_DEFAULT_PRIORITY`,
   `SALAD_GPU_NAMES` to avoid confusion. A missing setting now produces an error.
4. Rebuild Docker images (recreate alone is NOT a rebuild):
   `docker compose up -d --build --force-recreate backend frontend`.
5. Read-only inspection: `bash scripts/salad-deploy.sh`.
6. Create the missing Queue/Group or repair supported drift:
   `bash scripts/salad-deploy.sh --apply`.

The script first GETs the exact Queue/Group. On `name_conflict` + GET=404,
it retries GET and POST until the configured timeout. If Salad keeps the
name reserved, set a *different* `SALAD_CONTAINER_GROUP_NAME` in `.env`;
never change the Queue name just to work around an old group-name reservation.
It neither creates priority tiers nor deletes other groups/queues, nor
changes the replica count of an existing group. It will not silently
reconnect an existing group to a different Queue.

## Important scope

This package does **not** alter `salad-worker/Dockerfile`, the
`qwen-vast-recovery` installer, its pinned Git commit, model files or LoRAs.
The configured `fp8-baked` worker image is NOT the same as the generic PyTorch
image used during the successful interactive installation test. Verify the
worker's end-to-end readiness and a real job before production use.

## Tests

`python3 -m unittest discover -s tests -p 'test_medium_deployment.py' -v`

Tests use mocked Salad API calls: they do not create cloud resources.
