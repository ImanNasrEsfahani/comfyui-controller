ARG COMFY_API_IMAGE=ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime
FROM ${COMFY_API_IMAGE}

USER root

ARG MODEL_PROFILE=fp8
ARG QVR_REPO=https://github.com/ImanNasrEsfahani/qwen-vast-recovery.git
ARG QVR_COMMIT=4e8d67097bb469e499f35ab84c6d752c29414157
ARG REACTOR_REPO=https://github.com/Gourieff/ComfyUI-ReActor.git
ARG REACTOR_COMMIT=a12c5b19dcac9ae8b47e592da39c9711c8f8c756
ARG SALAD_JOB_QUEUE_WORKER_VERSION=0.7.0

# The two largest Qwen files are baked into the image.
# This moves ~30 GB of model transfer out of every runtime cold start and
# into the one-time image build/pull path.
ARG FP8_MODEL_URL=https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors
ARG FP8_MODEL_SHA256=c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e
ARG INT8_MODEL_URL=https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors
ARG INT8_MODEL_SHA256=11b5af5ac601821d73930c84846c9a158e67177356daf927ce1c8d10f3963829
ARG TEXT_ENCODER_URL=https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors
ARG TEXT_ENCODER_SHA256=cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential python3-dev git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PIP_CONSTRAINT=/opt/pytorch-constraints.txt
ENV UV_CONSTRAINT=/opt/pytorch-constraints.txt

RUN git clone --filter=blob:none "${QVR_REPO}" /opt/qvr && \
    git -C /opt/qvr checkout --detach "${QVR_COMMIT}"

RUN rm -rf /opt/ComfyUI/custom_nodes/ComfyUI-ReActor && \
    git clone "${REACTOR_REPO}" /opt/ComfyUI/custom_nodes/ComfyUI-ReActor && \
    git -C /opt/ComfyUI/custom_nodes/ComfyUI-ReActor checkout --detach "${REACTOR_COMMIT}" && \
    python -m pip install --no-cache-dir "setuptools==81.0.0" && \
    python -m pip install --no-cache-dir -r /opt/ComfyUI/custom_nodes/ComfyUI-ReActor/requirements.txt && \
    cd /opt/ComfyUI/custom_nodes/ComfyUI-ReActor && \
    python install.py && \
    python -m pip uninstall -y onnxruntime onnxruntime-gpu || true && \
    python -m pip install --no-cache-dir "setuptools==81.0.0" "onnxruntime-gpu>=1.27,<2" && \
    rm -rf /root/.cache/pip

RUN mkdir -p /opt/ComfyUI/user/default/workflows/qwen2511 && \
    cp -R /opt/qvr/workflows/* /opt/ComfyUI/user/default/workflows/qwen2511/

ADD https://github.com/SaladTechnologies/salad-cloud-job-queue-worker/releases/download/v${SALAD_JOB_QUEUE_WORKER_VERSION}/salad-http-job-queue-worker_x86_64.tar.gz /tmp/salad-worker.tar.gz
RUN tar -C /usr/local/bin -zxpf /tmp/salad-worker.tar.gz && \
    rm -f /tmp/salad-worker.tar.gz

# Bake the two dominant model files into the image. Safetensors are already
# dense, so this is intentionally kept to only the files that save the most
# runtime download time while staying under Salad's image-size ceiling.
RUN set -Eeux; \
    mkdir -p \
      /opt/ComfyUI/models/diffusion_models \
      /opt/ComfyUI/models/text_encoders; \
    download_verify() { \
      url="$1"; dst="$2"; expected="$3"; \
      tmp="${dst}.partial"; \
      rm -f "$tmp"; \
      curl -fL \
        --retry 8 \
        --retry-all-errors \
        --retry-delay 5 \
        --connect-timeout 30 \
        --speed-time 120 \
        --speed-limit 1024 \
        "$url" -o "$tmp"; \
      actual="$(sha256sum "$tmp" | awk '{print $1}')"; \
      test "$actual" = "$expected"; \
      mv "$tmp" "$dst"; \
    }; \
    if [ "${MODEL_PROFILE}" = "fp8" ]; then \
      download_verify \
        "${FP8_MODEL_URL}" \
        /opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors \
        "${FP8_MODEL_SHA256}"; \
    elif [ "${MODEL_PROFILE}" = "int8" ]; then \
      download_verify \
        "${INT8_MODEL_URL}" \
        /opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors \
        "${INT8_MODEL_SHA256}"; \
    else \
      echo "Unsupported MODEL_PROFILE=${MODEL_PROFILE}" >&2; \
      exit 1; \
    fi; \
    download_verify \
      "${TEXT_ENCODER_URL}" \
      /opt/ComfyUI/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors \
      "${TEXT_ENCODER_SHA256}"; \
    du -h \
      /opt/ComfyUI/models/diffusion_models/* \
      /opt/ComfyUI/models/text_encoders/*

COPY manifest.fp8.yaml /opt/qvr-salad/manifest.fp8.yaml
COPY manifest.fp8-full.yaml /opt/qvr-salad/manifest.fp8-full.yaml
COPY manifest.int8.yaml /opt/qvr-salad/manifest.int8.yaml
COPY manifest.int8-full.yaml /opt/qvr-salad/manifest.int8-full.yaml

RUN test -f "/opt/qvr-salad/manifest.${MODEL_PROFILE}.yaml" && \
    cp "/opt/qvr-salad/manifest.${MODEL_PROFILE}.yaml" /opt/qvr-salad/manifest.yaml

COPY --chmod=755 start.sh /opt/qvr-salad/start.sh
COPY --chmod=755 verify_runtime.sh /opt/qvr-salad/verify_runtime.sh

# Remove build-only packages to keep the final compressed image below the
# SaladCloud image-size limit.
RUN apt-get purge -y --auto-remove build-essential python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

ENV MANIFEST=/opt/qvr-salad/manifest.yaml
ENV PORT=3000
ENV LRU_CACHE_SIZE_GB=40
ENV SALAD_LOG_LEVEL=info
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_XET_HIGH_PERFORMANCE=1

# comfyui-api startup checking.
ENV STARTUP_CHECK_MAX_TRIES=360
ENV STARTUP_CHECK_INTERVAL_S=5

# Our wrapper no longer kills a healthy instance after only 10 minutes.
ENV READY_TIMEOUT_SECONDS=1800
ENV READY_POLL_SECONDS=5

CMD ["/opt/qvr-salad/start.sh"]
