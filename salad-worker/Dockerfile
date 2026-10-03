# syntax=docker/dockerfile:1
ARG COMFY_API_IMAGE=ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime
FROM ${COMFY_API_IMAGE}

USER root

ARG QVR_REPO=https://github.com/ImanNasrEsfahani/qwen-vast-recovery.git
ARG QVR_COMMIT=4e8d67097bb469e499f35ab84c6d752c29414157
ARG REACTOR_REPO=https://github.com/Gourieff/ComfyUI-ReActor.git
ARG REACTOR_COMMIT=a12c5b19dcac9ae8b47e592da39c9711c8f8c756
ARG SALAD_JOB_QUEUE_WORKER_VERSION=0.7.0

# Deliberately bake only the FP8 diffusion model and its REQUIRED text encoder.
# INT8 is an alternative to FP8, not an additional runtime requirement.
# Each download RUN creates at most one 3.0-GB data layer; the worker reassembles
# the two original safetensors files locally before starting comfyui-api.
# libgl1 supplies libGL.so.1, required by ReActor's OpenCV (cv2) import.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential python3-dev git curl ca-certificates libgl1 && \
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

# Fail the GitHub Actions build immediately if ReActor/OpenCV is still missing
# a native runtime library; do not discover it after pulling 30 GB on Salad.
RUN python -c "import cv2; print('OpenCV loaded:', cv2.__version__)"

RUN mkdir -p /opt/ComfyUI/user/default/workflows/qwen2511 && \
    cp -R /opt/qvr/workflows/* /opt/ComfyUI/user/default/workflows/qwen2511/

ADD https://github.com/SaladTechnologies/salad-cloud-job-queue-worker/releases/download/v${SALAD_JOB_QUEUE_WORKER_VERSION}/salad-http-job-queue-worker_x86_64.tar.gz /tmp/salad-worker.tar.gz
RUN tar -C /usr/local/bin -zxpf /tmp/salad-worker.tar.gz && \
    rm -f /tmp/salad-worker.tar.gz

COPY --chmod=755 model_parts.py /opt/qvr-salad/model_parts.py

# Important: each of these is a SEPARATE Docker layer. Do not combine into
# one RUN, or the ~24.5-GB single layer returns.
RUN python /opt/qvr-salad/model_parts.py download fp8 0
RUN python /opt/qvr-salad/model_parts.py download fp8 1
RUN python /opt/qvr-salad/model_parts.py download fp8 2
RUN python /opt/qvr-salad/model_parts.py download fp8 3
RUN python /opt/qvr-salad/model_parts.py download fp8 4
RUN python /opt/qvr-salad/model_parts.py download fp8 5
RUN python /opt/qvr-salad/model_parts.py download fp8 6
RUN python /opt/qvr-salad/model_parts.py download fp8 7
RUN python /opt/qvr-salad/model_parts.py download fp8 8

RUN python /opt/qvr-salad/model_parts.py download encoder 0
RUN python /opt/qvr-salad/model_parts.py download encoder 1
RUN python /opt/qvr-salad/model_parts.py download encoder 2
RUN python /opt/qvr-salad/model_parts.py download encoder 3

# Stream SHA256 across parts WITHOUT joining them in a new giant Docker layer.
RUN python /opt/qvr-salad/model_parts.py verify fp8 && \
    python /opt/qvr-salad/model_parts.py verify encoder

# The selected FP8 profile; no unnecessary INT8 manifest or INT8 base model.
COPY manifest.fp8.yaml /opt/qvr-salad/manifest.yaml
COPY manifest.fp8-full.yaml /opt/qvr-salad/manifest.fp8-full.yaml
COPY --chmod=755 start.sh /opt/qvr-salad/start.sh
COPY --chmod=755 verify_runtime.sh /opt/qvr-salad/verify_runtime.sh

RUN apt-get purge -y --auto-remove build-essential python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

ENV MANIFEST=/opt/qvr-salad/manifest.yaml
ENV PORT=3000
ENV LRU_CACHE_SIZE_GB=40
ENV SALAD_LOG_LEVEL=info
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV HF_XET_HIGH_PERFORMANCE=1
ENV STARTUP_CHECK_MAX_TRIES=360
ENV STARTUP_CHECK_INTERVAL_S=5
ENV READY_TIMEOUT_SECONDS=1800
ENV READY_POLL_SECONDS=5

CMD ["/opt/qvr-salad/start.sh"]
