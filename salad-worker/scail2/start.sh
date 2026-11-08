#!/usr/bin/env bash
set -Eeuo pipefail
if [ "${SCAIL2_BAKE_MODE:-thin}" = thin ]; then
  echo '[scail2] thin image: downloading/verifying weights into ComfyUI models directory'
  python /opt/scail2/download_models.py
else
  echo '[scail2] baked image: restoring verified model parts onto local SSD'
  python /opt/scail2/model_parts.py restore
fi
find_api() {
  for bin in "${COMFYUI_API_BIN:-}" "$(command -v comfyui-api || true)" /opt/ComfyUI/comfyui-api /app/comfyui-api /comfyui-api; do
    if [ -n "$bin" ] && [ -x "$bin" ]; then echo "$bin";return 0; fi
  done
  return 1
}
API_BIN="$(find_api)" || { echo '[scail2] comfyui-api executable not found';exit 127; }
"$API_BIN" & API_PID=$!
cleanup(){ kill "${WORKER_PID:-}" "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT TERM INT
started="$(date +%s)"
while ! curl -fsS "http://127.0.0.1:${PORT:-3000}/ready" >/dev/null; do
  if ! kill -0 "$API_PID" 2>/dev/null; then echo '[scail2] API exited';exit 1; fi
  if (( $(date +%s)-started > ${READY_TIMEOUT_SECONDS:-1800} )); then echo '[scail2] readiness timeout';exit 1; fi
  sleep 5
done
python - <<'PY'
import sys
sys.path.insert(0,'/opt/scail2')
from worker import runtime_ready
missing=runtime_ready()
if missing:raise SystemExit('Missing ComfyUI nodes: '+', '.join(missing))
print('[scail2] required node classes available')
PY
python /opt/scail2/worker.py & WORKER_PID=$!
wait -n "$WORKER_PID" "$API_PID"
