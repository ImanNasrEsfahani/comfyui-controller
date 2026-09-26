# Salad GPU Worker

This directory is the ephemeral compute plane.

## Why ReActor is baked but Qwen weights are not

The current upstream recovery repo requires ReActor's official `install.py`, a pinned commit, and CUDA-sensitive ONNX Runtime behavior.

The Salad manifest mechanism is ideal for model weights, but the ReActor hardening is safer at Docker build time.

Therefore:

```text
Docker image:
  ComfyUI API
  ReActor code/dependencies
  Salad Job Queue Worker
  QVR workflow reference files

Runtime manifest:
  Qwen base
  text encoder
  VAE
  Lightning LoRA
  InsightFace swap model
  optional LoRAs
```

## Build FP8

```bash
docker build \
  --build-arg MODEL_PROFILE=fp8 \
  -t ghcr.io/YOU/qwen-comfyui-salad:fp8 .
```

## Build INT8

```bash
docker build \
  --build-arg MODEL_PROFILE=int8 \
  -t ghcr.io/YOU/qwen-comfyui-salad:int8 .
```

## R2 environment

The worker needs:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION=auto
AWS_ENDPOINT_URL_S3=https://<account-id>.r2.cloudflarestorage.com
```

The deployment script also sets the global `AWS_ENDPOINT_URL` as a compatibility fallback.

## Job Queue

`queue_connection.path` is `/prompt` and port is `3000`.

This means the Salad Job Queue Worker takes the queue job's `input` object and sends it to:

```text
http://127.0.0.1:3000/prompt
```

The backend deliberately creates a payload that is already valid for this endpoint.

## Cold start

All essential files are in `before_start`.

Optional LoRAs are in `after_start`.

This avoids a worker becoming Ready before its required Qwen/ReActor assets exist, while not making every optional LoRA block readiness.


## Core vs full profile

The default `fp8` and `int8` profiles download only assets required by the current recovery repository.

Optional portrait/NSFW LoRAs are intentionally **not** downloaded on every scale-from-zero cold start.

If you explicitly want the whole optional set preloaded:

```bash
docker build --build-arg MODEL_PROFILE=fp8-full ...
```

or:

```bash
docker build --build-arg MODEL_PROFILE=int8-full ...
```

For the cost-sensitive always-on-controller architecture, start with the core profile.
