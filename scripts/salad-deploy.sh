#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
    echo "ERROR: $ROOT_DIR/.env does not exist." >&2
    echo "Create it from .env.example and add secrets first." >&2
    exit 1
fi

set -a
source .env
set +a

export SALAD_ORG="${SALAD_ORG:-imanprojects}"
export SALAD_PROJECT="${SALAD_PROJECT:-comfy}"
export SALAD_QUEUE="${SALAD_QUEUE:-qwen-comfyui}"
export SALAD_CONTAINER_GROUP="${SALAD_CONTAINER_GROUP:-qwen-comfyui-fp8}"
export SALAD_IMAGE="${SALAD_IMAGE:-ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8}"
export SALAD_GPU_NAMES="${SALAD_GPU_NAMES:-RTX 4090 (24 GB),RTX 5090 (32 GB)}"
export SALAD_PRIORITY="${SALAD_PRIORITY:-batch}"
export SALAD_INITIAL_REPLICAS="${SALAD_INITIAL_REPLICAS:-0}"
export SALAD_MIN_REPLICAS="${SALAD_MIN_REPLICAS:-0}"
export SALAD_MAX_REPLICAS="${SALAD_MAX_REPLICAS:-1}"
export SALAD_DESIRED_QUEUE_LENGTH="${SALAD_DESIRED_QUEUE_LENGTH:-1}"
export SALAD_POLLING_PERIOD="${SALAD_POLLING_PERIOD:-30}"

: "${SALAD_API_KEY:?SALAD_API_KEY is required in .env}"
: "${R2_ENDPOINT_URL:?R2_ENDPOINT_URL is required in .env}"
: "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required in .env}"
: "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required in .env}"

exec python3 salad-worker/deploy_salad.py "$@"
