#!/bin/sh
# Start the job API at once (it answers /health, "not ready" until the weights are checked and ComfyUI is up), then
# fetch the pinned weights and start ComfyUI on 127.0.0.1 only. Any failure is written to the state dir and shown on
# /health; the studio then terminates the pod (it never waits past its boot timeout).
set -u
mkdir -p "$WORKER_STATE_DIR" "$WORKER_ROOT"
rm -f "$WORKER_STATE_DIR/ready" "$WORKER_STATE_DIR/failed"
/opt/venv/bin/python /app/server.py &
API=$!
if [ "${WORKER_BACKEND:-comfyui}" = "stub" ]; then
  touch "$WORKER_STATE_DIR/ready"
else
  if ! /opt/venv/bin/python /app/fetch_models.py /app/models.lock "$MODELS_DIR" > "$WORKER_STATE_DIR/fetch.log" 2>&1; then
    tail -c 300 "$WORKER_STATE_DIR/fetch.log" > "$WORKER_STATE_DIR/failed"
  else
    ln -sfn "$MODELS_DIR" "$COMFYUI_DIR/models/oddstudio"
    (cd "$COMFYUI_DIR" && /opt/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch > "$WORKER_STATE_DIR/comfyui.log" 2>&1) &
    i=0
    until /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=5)" 2>/dev/null; do
      i=$((i + 1)); [ "$i" -gt 180 ] && { echo "ComfyUI did not start within 15 minutes" > "$WORKER_STATE_DIR/failed"; break; }
      sleep 5
    done
    [ -f "$WORKER_STATE_DIR/failed" ] || touch "$WORKER_STATE_DIR/ready"
  fi
fi
wait $API
