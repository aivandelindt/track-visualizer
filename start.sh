#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/visualizer.pid"
LOG_FILE="$RUN_DIR/visualizer.log"
URL="${VISUALIZER_URL:-http://127.0.0.1:8000/index.html}"

mkdir -p "$RUN_DIR"

find_listening_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:8000 -sTCP:LISTEN 2>/dev/null | head -n 1
  fi
}

report_existing_server() {
  local pid="$1"
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "Visualizer already running on $URL (pid $pid)."
    if command -v open >/dev/null 2>&1; then
      open "$URL" >/dev/null 2>&1 || true
    fi
    exit 0
  fi
}

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE")"
  report_existing_server "$existing_pid"
  rm -f "$PID_FILE"
fi

listening_pid="$(find_listening_pid || true)"
if [[ -n "$listening_pid" ]]; then
  listening_cmd="$(ps -p "$listening_pid" -o command= 2>/dev/null || true)"
  if [[ "$listening_cmd" == *"server.py"* ]]; then
    echo "$listening_pid" >"$PID_FILE"
    report_existing_server "$listening_pid"
  fi

  echo "Port 8000 is already in use by pid $listening_pid. Stop that process before starting the visualizer."
  exit 1
fi

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python"
  fi
fi

nohup "$python_bin" "$ROOT_DIR/server.py" >"$LOG_FILE" 2>&1 &
server_pid=$!
echo "$server_pid" >"$PID_FILE"

echo "Started visualizer on $URL (pid $server_pid)."
echo "Log: $LOG_FILE"

if command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 || true
fi
