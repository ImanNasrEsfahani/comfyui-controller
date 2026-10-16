#!/usr/bin/env bash
set -Eeuo pipefail

# Cold-start timeline is intentionally structured and free of credentials.
# These numbers begin AFTER Salad has pulled/extracted the OCI image; Salad's
# image pull and node allocation times must be measured with its provider API.
COLDSTART_EPOCH="$(date +%s)"
log_phase() {
  local event="$1"
  local now
  now="$(date +%s)"
  printf '[coldstart] event=%s utc=%s elapsed_s=%s\n' \
    "$event" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$((now - COLDSTART_EPOCH))"
}

# Model data arrives as small Docker layers. Assemble on the local SSD, never
# redownload it at cold start, and fail closed on missing/corrupt chunks.
log_phase "container_entry"
echo "[qvr-salad] restoring FP8 and encoder assets from verified model parts..."
log_phase "model_restore_start"
python /opt/qvr-salad/model_parts.py restore
log_phase "model_restore_done"

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
  log_phase "api_binary_missing"
  echo "[qvr-salad] ERROR: comfyui-api binary not found" >&2
  exit 127
fi

READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-1800}"
READY_POLL_SECONDS="${READY_POLL_SECONDS:-5}"

echo "[qvr-salad] starting comfyui-api: $API_BIN"
echo "[qvr-salad] manifest: ${MANIFEST:-unset}"
echo "[qvr-salad] ready timeout: ${READY_TIMEOUT_SECONDS}s"
log_phase "api_start"
"$API_BIN" &
API_PID=$!
cleanup() {
  kill "${WORKER_PID:-}" "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

echo "[qvr-salad] waiting for /ready before connecting to the direct backend..."
started_at="$(date +%s)"
last_progress=0
while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    log_phase "api_exited_before_ready"
    echo "[qvr-salad] ERROR: comfyui-api exited during startup" >&2
    wait "$API_PID" || true
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:${PORT:-3000}/ready" >/dev/null 2>&1; then
    elapsed="$(( $(date +%s) - started_at ))"
    log_phase "api_ready"
    echo "[qvr-salad] /ready is healthy after ${elapsed}s"
    break
  fi
  now="$(date +%s)"
  elapsed="$(( now - started_at ))"
  if (( elapsed >= READY_TIMEOUT_SECONDS )); then
    log_phase "api_ready_timeout"
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
log_phase "runtime_verification_start"
/opt/qvr-salad/verify_runtime.sh
log_phase "runtime_verified"

echo "[qvr-salad] runtime verified; starting direct pull worker (no IMDS)"
python /opt/qvr-salad/pull_worker.py &
WORKER_PID=$!
log_phase "direct_worker_spawned"

set +e
wait -n "$WORKER_PID" "$API_PID"
RC=$?
set -e
log_phase "critical_process_exited"
echo "[qvr-salad] a critical process exited: $RC" >&2
exit "$RC"
