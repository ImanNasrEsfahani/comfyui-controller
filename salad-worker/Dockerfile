ARG COMFY_API_IMAGE=ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime
FROM ${COMFY_API_IMAGE}

USER root

ARG MODEL_PROFILE=fp8
ARG QVR_REPO=https://github.com/ImanNasrEsfahani/qwen-vast-recovery.git
ARG QVR_COMMIT=4e8d67097bb469e499f35ab84c6d752c29414157
ARG REACTOR_REPO=https://github.com/Gourieff/ComfyUI-ReActor.git
ARG REACTOR_COMMIT=a12c5b19dcac9ae8b47e592da39c9711c8f8c756
ARG SALAD_JOB_QUEUE_WORKER_VERSION=0.7.0

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential python3-dev git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Preserve the Torch/CUDA pair chosen by Salad's base image while installing
# third-party custom-node requirements.
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
    python -m pip install --no-cache-dir "setuptools==81.0.0" "onnxruntime-gpu>=1.27,<2"

RUN mkdir -p /opt/ComfyUI/user/default/workflows/qwen2511 && \
    cp -R /opt/qvr/workflows/* /opt/ComfyUI/user/default/workflows/qwen2511/

ADD https://github.com/SaladTechnologies/salad-cloud-job-queue-worker/releases/download/v${SALAD_JOB_QUEUE_WORKER_VERSION}/salad-http-job-queue-worker_x86_64.tar.gz /tmp/salad-worker.tar.gz
RUN tar -C /usr/local/bin -zxpf /tmp/salad-worker.tar.gz && \
    rm -f /tmp/salad-worker.tar.gz

COPY manifest.fp8.yaml /opt/qvr-salad/manifest.fp8.yaml
COPY manifest.fp8-full.yaml /opt/qvr-salad/manifest.fp8-full.yaml
COPY manifest.int8.yaml /opt/qvr-salad/manifest.int8.yaml
COPY manifest.int8-full.yaml /opt/qvr-salad/manifest.int8-full.yaml
RUN test -f "/opt/qvr-salad/manifest.${MODEL_PROFILE}.yaml" && \
    cp "/opt/qvr-salad/manifest.${MODEL_PROFILE}.yaml" /opt/qvr-salad/manifest.yaml

COPY --chmod=755 start.sh /opt/qvr-salad/start.sh
COPY --chmod=755 verify_runtime.sh /opt/qvr-salad/verify_runtime.sh

ENV MANIFEST=/opt/qvr-salad/manifest.yaml
ENV PORT=3000
ENV LRU_CACHE_SIZE_GB=40
ENV SALAD_LOG_LEVEL=info
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_XET_HIGH_PERFORMANCE=1
ENV STARTUP_CHECK_MAX_TRIES=120

CMD ["/opt/qvr-salad/start.sh"]
