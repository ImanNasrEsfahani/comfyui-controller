#!/usr/bin/env bash
set -Eeuo pipefail

python - <<'PY'
import onnxruntime as ort
providers = ort.get_available_providers()
print("onnxruntime:", ort.__version__)
print("providers:", providers)
if "CUDAExecutionProvider" not in providers:
    raise SystemExit("CUDAExecutionProvider is missing")
PY

check_sha() {
  local expected="$1"
  local path="$2"
  if [[ ! -f "$path" ]]; then
    echo "Missing required asset: $path" >&2
    exit 1
  fi
  local actual
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA256 mismatch: $path" >&2
    echo "expected=$expected" >&2
    echo "actual=$actual" >&2
    exit 1
  fi
  echo "OK sha256: $path"
}

# Common required assets from qwen-vast-recovery manifests.
check_sha "cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4" \
  "/opt/ComfyUI/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
check_sha "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f" \
  "/opt/ComfyUI/models/vae/qwen_image_vae.safetensors"
check_sha "22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f" \
  "/opt/ComfyUI/models/loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
check_sha "1a8f542a733b8b2d942d1535ef817835cf83a7f332eeeabef507676554a2b1a1" \
  "/opt/ComfyUI/models/loras/Qwen-Image-Edit-Unblur-Upscale_20.safetensors"
check_sha "e4a3f08c753cb72d04e10aa0f7dbe3deebbf39567d4ead6dce08e98aa49e16af" \
  "/opt/ComfyUI/models/insightface/inswapper_128.onnx"

if [[ -f /opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors ]]; then
  check_sha "c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e" \
    "/opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"
elif [[ -f /opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors ]]; then
  check_sha "11b5af5ac601821d73930c84846c9a158e67177356daf927ce1c8d10f3963829" \
    "/opt/ComfyUI/models/diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors"
else
  echo "No supported Qwen 2511 base model found" >&2
  exit 1
fi

# Confirm that ComfyUI actually registered the ReActor class used by the audited workflows.
if curl -fsS http://127.0.0.1:8188/object_info | grep -q '"ReActorFaceSwap"'; then
  echo "OK node: ReActorFaceSwap"
else
  echo "ReActorFaceSwap was not registered by ComfyUI" >&2
  exit 1
fi

curl -fsS "http://127.0.0.1:${PORT:-3000}/health" >/dev/null
curl -fsS "http://127.0.0.1:${PORT:-3000}/ready" >/dev/null
echo "Runtime verification passed."
