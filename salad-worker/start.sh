#!/usr/bin/env bash
set -Eeuo pipefail

find_api() {
  if [[ -n "${COMFYUI_API_BIN:-}" && -x "${COMFYUI_API_BIN}" ]]; then
    printf '%s\n' "${COMFYUI_API_BIN}"
    return 0
  fi
  if command -v comfyui-api >/dev/null 2>&1; then
    command -v comfyui-api
    return 0
  fi
  for p in \
    /opt/ComfyUI/comfyui-api \
    /app/comfyui-api \
    /comfyui-api \
    /usr/local/bin/comfyui-api \
    /opt/comfyui-api/comfyui-api
  do
    if [[ -x "$p" ]]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

API_BIN="$(find_api || true)"
if [[ -z "$API_BIN" ]]; then
  echo "[qvr-salad] ERROR: comfyui-api binary not found" >&2
  exit 127
fi

echo "[qvr-salad] starting comfyui-api: $API_BIN"
echo "[qvr-salad] manifest: ${MANIFEST:-unset}"
"$API_BIN" &
API_PID=$!

cleanup() {
  kill "${QUEUE_PID:-}" "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

echo "[qvr-salad] waiting for /ready before connecting to the Job Queue..."
READY=0
for i in $(seq 1 120); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[qvr-salad] ERROR: comfyui-api exited during startup" >&2
    wait "$API_PID" || true
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:${PORT:-3000}/ready" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 5
done

if [[ "$READY" != "1" ]]; then
  echo "[qvr-salad] ERROR: comfyui-api did not become ready" >&2
  exit 1
fi

echo "[qvr-salad] validating CUDA/ReActor/core asset integrity..."
/opt/qvr-salad/verify_runtime.sh

echo "[qvr-salad] runtime verified; starting Salad Job Queue Worker"
/usr/local/bin/salad-http-job-queue-worker &
QUEUE_PID=$!

wait -n "$QUEUE_PID" "$API_PID"
RC=$?
echo "[qvr-salad] a critical process exited: $RC" >&2
exit "$RC"
