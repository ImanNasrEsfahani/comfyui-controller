# Salad GPU Worker

This directory is the ephemeral GPU compute plane.

## Image

`ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8`

## GPU classes

Exact desktop classes only:

- RTX 4090 (24 GB)
- RTX 5090 (32 GB)

Exact matching prevents accidental selection of Laptop variants.

## Deploy

From repository root:

```bash
bash scripts/salad-deploy.sh
```

After reviewing dry-run output:

```bash
bash scripts/salad-deploy.sh --apply
```

The wrapper reads the root `.env`; temporary `export` commands are not needed.

## Secrets

Keep only in `.env`, never Git:

- SALAD_API_KEY
- R2_ACCESS_KEY_ID
- R2_SECRET_ACCESS_KEY
- HF_TOKEN (if used)

## Scale-to-zero defaults

- initial replicas: 0
- min replicas: 0
- max replicas: 1
- desired queue length: 1
- polling period: 30 seconds

`deploy_salad.py` also sends an explicit User-Agent for compatibility with Salad's Cloudflare edge.
