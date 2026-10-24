# ComfyUI image for a persistent RunPod Pod (and local runs, run-local.sh).
#
# A lightweight image: OS + one venv with ComfyUI core and a pinned torch stack,
# custom nodes pinned by commit (custom_nodes.txt) or our own (custom_nodes/),
# workflows, and start.sh. No models: those live on the volume (models.txt).
# Build with ./build.sh, not by hand: it tags by git sha (DESIGN.md "Image").
#
# Two builds:
#   default  cu130: CUDA 13 kernels (comfy-kitchen's int8/nvfp4 backends need
#            torch.version.cuda >= 13), but only hosts with driver >= 580.
#   --cu128  BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 CUDA_TAG=cu128:
#            runs on far more hosts (and older local drivers); quantized models fall
#            back to comfy-kitchen's eager (plain PyTorch) backend.
ARG BASE_IMAGE=nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04
FROM ${BASE_IMAGE}

ARG COMFYUI_REF=v0.41.3
ARG TORCH_VERSION=2.11.0
ARG TORCHVISION_VERSION=0.26.0
ARG TORCHAUDIO_VERSION=2.11.0
ARG CUDA_TAG=cu130
# Public port of the optional app (app/run.sh); nginx puts the password in front.
ARG APP_PORT=8770
ARG PROJECT=comfyui

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONNOUSERSITE=1 \
    APP_PORT=${APP_PORT} \
    PROJECT=${PROJECT}

# nginx + openssl: the password in front of ComfyUI, which has none of its own (start.sh).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates rsync util-linux unzip \
        python3 python3-venv python3-pip \
        nginx openssl \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch "${COMFYUI_REF}" --depth 1 \
        https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI
WORKDIR /opt/ComfyUI

RUN python3 -m venv venv \
    && ./venv/bin/pip install --no-input --upgrade pip setuptools wheel

# Torch first, from the CUDA index, so ComfyUI's unpinned "torch" requirement is
# already met and pip can't swap in a CPU or other-CUDA build. The constraints
# file then holds that torch in place for every custom node's requirements.
RUN ./venv/bin/pip install --no-input \
        --index-url "https://download.pytorch.org/whl/${CUDA_TAG}" \
        "torch==${TORCH_VERSION}+${CUDA_TAG}" \
        "torchvision==${TORCHVISION_VERSION}+${CUDA_TAG}" \
        "torchaudio==${TORCHAUDIO_VERSION}+${CUDA_TAG}" \
    && ./venv/bin/pip install --no-input --prefer-binary -r requirements.txt \
    && ./venv/bin/python -c "import torch; assert torch.__version__.startswith('${TORCH_VERSION}'), torch.__version__" \
    && ./venv/bin/pip freeze | grep -iE '^(torch|torchvision|torchaudio)==' > /opt/constraints.txt

# S3 client for MODELS_SOURCE=s3:<DC>:<volume> (start.sh), in its own venv.
RUN python3 -m venv /opt/awscli \
    && /opt/awscli/bin/pip install --no-input --prefer-binary awscli \
    && /opt/awscli/bin/aws --version

# System libraries that many node packs need: OpenCV (cv2) won't import without
# libxcb/libGL, and the CUDA runtime base image has neither.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Third-party custom nodes, each pinned to a commit or tag (custom_nodes.txt).
COPY custom_nodes.txt /opt/custom_nodes.txt
RUN set -e; \
    grep -vE '^\s*(#|$)' /opt/custom_nodes.txt | while read -r url ref _; do \
        name=$(basename "$url" .git); dir="custom_nodes/$name"; \
        echo "== $name @ $ref"; \
        git init -q "$dir"; git -C "$dir" remote add origin "$url"; \
        git -C "$dir" fetch -q --depth 1 origin "$ref"; git -C "$dir" checkout -q FETCH_HEAD; \
        rm -rf "$dir/.git"; \
        if [ -f "$dir/requirements.txt" ]; then \
            ./venv/bin/pip install --no-input --prefer-binary -c /opt/constraints.txt -r "$dir/requirements.txt"; \
        fi; \
    done

# Our own nodes (small, reviewed, in this repo).
COPY custom_nodes/ /opt/ComfyUI/custom_nodes/

# Fail the build if any node pack doesn't import (ComfyUI only logs a warning).
# --cpu: no GPU at build time. The torch check catches a requirement that swapped it anyway.
RUN ./venv/bin/python main.py --cpu --quick-test-for-ci > /tmp/quick-test.log 2>&1 \
    || { cat /tmp/quick-test.log; exit 1; }; \
    if grep -q "IMPORT FAILED" /tmp/quick-test.log; then \
        grep -A15 -E "Traceback|Cannot import" /tmp/quick-test.log | head -200; grep "IMPORT FAILED" /tmp/quick-test.log; exit 1; \
    fi; \
    ./venv/bin/python -c "import torch; assert '${CUDA_TAG}' in torch.__version__, torch.__version__"; \
    rm -rf user output input temp

# Optional app next to ComfyUI: app/install.sh runs here (give it its own venv,
# so its pins can't touch ComfyUI's); start.sh starts app/run.sh.
COPY app/ /opt/app/
RUN if [ -f /opt/app/install.sh ]; then bash /opt/app/install.sh; fi

# start.sh seeds these into the Workflows sidebar without overwriting edited copies.
COPY workflows/ /opt/workflows/
COPY start.sh models.txt tools/fetch-models.sh /opt/ComfyUI/
RUN chmod +x start.sh fetch-models.sh

EXPOSE 8188 ${APP_PORT}
ENTRYPOINT ["/opt/ComfyUI/start.sh"]
