# Salad GPU Worker — one Medium group only

One queue and one queue-autoscaled, scale-to-zero Container Group:

- Queue: `qwen-comfyui-medium`
- Container Group: `qwen-comfyui-fp8-medium`
- Priority: `medium`
- GPU class: **only RTX 5090 (32 GB VRAM)**
- 4 vCPU; **30 GB system RAM** (30720 MB); 2048 MB shared memory; **100 GB disk**
- Replicas: initial=0, min=0, max=1; a queued job can request one GPU replica.
- Worker image: `ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8-baked`

**Important:** The worker image above is the existing baked ComfyUI API/Job Queue worker.
It is **not** the generic `pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime`
image used in the successful interactive *installation-only* test. This deployment
change does not certify that the worker image has the exact tested runtime.
The `qwen-vast-recovery` installer and its pinned commit are left untouched.

## Apply to a full repository checkout

1. Extract the supplied replacement ZIP over the root of `comfyui-controller`.
2. Run `python3 scripts/apply-medium-frontend.py` to update the existing `frontend/src/App.jsx`.
3. Merge updated values from `.env.example` into the existing, secret-bearing `.env`.
   **Never commit `.env`.** Keep `SALAD_API_KEY`, R2 credentials and tokens local.
4. Commit and push the modified tracked files (`git add ...`, then `git commit` and `git push`).
5. On the server, `git pull`; merge runtime `.env` values; rebuild frontend/backend:
   `docker compose up -d --build backend frontend`.
6. In a shell at the repo root, check without making changes:
   `bash scripts/salad-deploy.sh --priority medium`
7. After inspecting the output, apply:
   `bash scripts/salad-deploy.sh --apply --priority medium`

The deployer first checks GET for the Queue and group. Missing resources are
created; an existing Medium group is verified and has supported image/resource/
probe/autoscaler configuration drift patched. Running replicas are **not**
automatically started or stopped. Re-running is safe. A conflicting existing
`queue_connection` triggers a clear error instead of a destructive repair.

## Removing the old groups safely

Ensure old high/low/batch/legacy jobs are finished or cancelled **before** deleting
old queues. Stop and manually delete the old `High`, `Low`, `Batch Lowest`,
`Scale-to-Zero`, and `qvr-install-test` groups in the Salad Portal. The Medium
group can be retained (the script reconciles its 16 GB/50 GB/4090+5090 settings)
or deleted too, in which case `--apply` recreates it. Remove obsolete queues
only after historical jobs are no longer needed.

**The deployment script never deletes any group or queue automatically.**

## Notes

- Cloud GPU priority **Medium** is fixed. The Backend rejects new jobs
  requesting other priorities, and the UI exposes only Medium.
- `--apply` uses Salad API and requires a real `SALAD_API_KEY`; offline tests only
  validate the code and mock requests.
- With 0 replicas, the group does not continuously run a GPU. Autoscaling and
  image/model cold starts still incur startup latency and billed runtime.
