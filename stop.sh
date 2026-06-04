#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/visualizer.pid"

stop_pid() {
  local pid="$1"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid"
    echo "Stopped visualizer process $pid."
    return 0
  fi
  return 1
}

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if stop_pid "$pid"; then
    rm -f "$PID_FILE"
    exit 0
  fi

  rm -f "$PID_FILE"
fi

mapfile -t fallback_pids < <(pgrep -f "server\.py" || true)
for pid in "${fallback_pids[@]}"; do
  if stop_pid "$pid"; then
    continue
  fi
done

echo "No running visualizer process found."
