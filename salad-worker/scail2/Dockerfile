# syntax=docker/dockerfile:1
# A DIFFERENT worker image from the Qwen Image Edit worker. RTX 5090 recommended.
# Only source is stored in Git; Github Actions creates GHCR OCI image.
ARG COMFY_API_IMAGE=ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime
FROM ${COMFY_API_IMAGE}
USER root
ENV PIP_CONSTRAINT=/opt/pytorch-constraints.txt
ENV UV_CONSTRAINT=/opt/pytorch-constraints.txt
ARG BAKE_MODE=thin
# SCAIL-2/SAM3 native nodes were added after the old ComfyUI 0.35 runtime.
# Pin current core; never silently assume native nodes exist in the base.
ARG COMFYUI_REF=bdb0816a292d221efeb6ec4ae41bcdff3f91fc86
ARG KJ_REF=ab72eda7ffad6280422d71ab7d54d3fb87c0ba18
ARG VHS_REF=4d907bee61e92c2e65af3bd6383a4e4d356126d1
ARG EASY_REF=b0b47ca1372117fce575d9e744655344ebff6bef
ARG PYSS_REF=609f3afaa74b2f88ef9ce8d939626065e3247469
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0t64 && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir 'huggingface_hub>=0.35,<2' 'websocket-client>=1.8,<2'
RUN set -eux; \
    if [ -d /opt/ComfyUI/.git ]; then \
      git -C /opt/ComfyUI fetch --depth 1 origin "$COMFYUI_REF"; \
      git -C /opt/ComfyUI checkout --detach FETCH_HEAD; \
    else \
      git clone --filter=blob:none https://github.com/Comfy-Org/ComfyUI.git /tmp/scail2-comfy-core; \
      git -C /tmp/scail2-comfy-core fetch --depth 1 origin "$COMFYUI_REF"; \
      git -C /tmp/scail2-comfy-core checkout --detach FETCH_HEAD; \
      cp -a /tmp/scail2-comfy-core/. /opt/ComfyUI/; \
      rm -rf /tmp/scail2-comfy-core; \
    fi; \
    test -f /opt/ComfyUI/comfy_extras/nodes_scail.py; \
    test -f /opt/ComfyUI/comfy_extras/nodes_sam3.py; \
    python -m pip install --no-cache-dir -r /opt/ComfyUI/requirements.txt
RUN set -eux; \
    git clone --no-checkout https://github.com/kijai/ComfyUI-KJNodes.git /opt/ComfyUI/custom_nodes/ComfyUI-KJNodes; \
    git -C /opt/ComfyUI/custom_nodes/ComfyUI-KJNodes checkout "$KJ_REF"; \
    git clone --no-checkout https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git /opt/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite; \
    git -C /opt/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite checkout "$VHS_REF"; \
    git clone --no-checkout https://github.com/yolain/ComfyUI-Easy-Use.git /opt/ComfyUI/custom_nodes/ComfyUI-Easy-Use; \
    git -C /opt/ComfyUI/custom_nodes/ComfyUI-Easy-Use checkout "$EASY_REF"; \
    git clone --no-checkout https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git /opt/ComfyUI/custom_nodes/ComfyUI-Custom-Scripts; \
    git -C /opt/ComfyUI/custom_nodes/ComfyUI-Custom-Scripts checkout "$PYSS_REF"
# Base has torch/CUDA; use its constraints to avoid unintentionally replacing CUDA runtime.
RUN set -eux; for node in ComfyUI-KJNodes ComfyUI-VideoHelperSuite ComfyUI-Easy-Use ComfyUI-Custom-Scripts; do \
    if [ -f "/opt/ComfyUI/custom_nodes/$node/requirements.txt" ]; then \
        python -m pip install --no-cache-dir -r "/opt/ComfyUI/custom_nodes/$node/requirements.txt"; \
    fi; \
    done
COPY salad-worker/scail2/ /opt/scail2/
RUN python /opt/scail2/fetch_workflow.py
# Baked mode uses 2 GiB OCI layers; no 33 GB single layer. Requires a large runner.

RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 1; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 2; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 3; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 4; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 5; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 6; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 7; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 8; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 9; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 10; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 11; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 12; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 13; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 14; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 15; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice diffusion 16; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 1; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 2; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 3; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 4; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 5; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice text_encoder 6; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice sam3 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice sam3 1; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice vae 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice clip_vision 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice clip_vision 1; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice dpo_lora 0; fi
RUN --mount=type=cache,target=/root/.cache/huggingface --mount=type=secret,id=HF_TOKEN \
    if [ "$BAKE_MODE" = baked ]; then HF_TOKEN="$(cat /run/secrets/HF_TOKEN 2>/dev/null || true)" python /opt/scail2/model_parts.py slice fast_lora 0; fi
# Fail the large-runner build before publishing if a shard or artifact is missing.
RUN if [ "$BAKE_MODE" = baked ]; then python /opt/scail2/model_parts.py verify; fi
ENV PORT=3000
ENV SCAIL2_BAKE_MODE=${BAKE_MODE}
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_XET_HIGH_PERFORMANCE=1
ENV READY_TIMEOUT_SECONDS=1800
ENV MANIFEST=/opt/scail2/manifest.yaml
COPY salad-worker/scail2/manifest.yaml /opt/scail2/manifest.yaml
COPY --chmod=755 salad-worker/scail2/start.sh /opt/scail2/start.sh
CMD ["/opt/scail2/start.sh"]
