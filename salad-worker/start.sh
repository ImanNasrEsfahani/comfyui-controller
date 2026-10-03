#!/usr/bin/env bash
set -Eeuo pipefail

# Model data arrives as small Docker layers. Assemble on the local SSD, never
# redownload it at cold start, and fail closed on missing/corrupt chunks.
echo "[qvr-salad] restoring FP8 and encoder assets from verified model parts..."
python /opt/qvr-salad/model_parts.py restore

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

READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-1800}"
READY_POLL_SECONDS="${READY_POLL_SECONDS:-5}"

echo "[qvr-salad] starting comfyui-api: $API_BIN"
echo "[qvr-salad] manifest: ${MANIFEST:-unset}"
echo "[qvr-salad] ready timeout: ${READY_TIMEOUT_SECONDS}s"

"$API_BIN" &
API_PID=$!
cleanup() {
  kill "${QUEUE_PID:-}" "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

echo "[qvr-salad] waiting for /ready before connecting to the Job Queue..."
started_at="$(date +%s)"
last_progress=0
while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[qvr-salad] ERROR: comfyui-api exited during startup" >&2
    wait "$API_PID" || true
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:${PORT:-3000}/ready" >/dev/null 2>&1; then
    elapsed="$(( $(date +%s) - started_at ))"
    echo "[qvr-salad] /ready is healthy after ${elapsed}s"
    break
  fi
  now="$(date +%s)"
  elapsed="$(( now - started_at ))"
  if (( elapsed >= READY_TIMEOUT_SECONDS )); then
    echo "[qvr-salad] ERROR: /ready did not become healthy within ${READY_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  if (( elapsed - last_progress >= 30 )); then
    echo "[qvr-salad] still waiting for /ready: ${elapsed}s elapsed"
    last_progress="$elapsed"
  fi
  sleep "$READY_POLL_SECONDS"
done

echo "[qvr-salad] validating CUDA/ReActor/core asset integrity..."
/opt/qvr-salad/verify_runtime.sh

echo "[qvr-salad] runtime verified; starting Salad Job Queue Worker"
/usr/local/bin/salad-http-job-queue-worker &
QUEUE_PID=$!

wait -n "$QUEUE_PID" "$API_PID"
RC=$?
echo "[qvr-salad] a critical process exited: $RC" >&2
exit "$RC"
