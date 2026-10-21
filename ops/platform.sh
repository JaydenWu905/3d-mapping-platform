#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Machine-specific GLIM settings are data for the Pose adapter.  ROS setup and
# actual LD_LIBRARY_PATH are applied only by its GLIM/bridge child shells.
if [[ -f "$ROOT/ops/glim-runtime.env" ]]; then
  source "$ROOT/ops/glim-runtime.env"
fi
if [[ -f "$ROOT/ops/platform.local.env" ]]; then
  source "$ROOT/ops/platform.local.env"
fi
RUN_DIR="$ROOT/.run"
LOG_DIR="$ROOT/logs"
BACKEND_PORT=8000
FRONTEND_PORT=5173

mkdir -p "$RUN_DIR" "$LOG_DIR"

pid_matches() {
  local name="$1" pid="$2" expected_dir="$3" expected_arg="$4"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -d "/proc/$pid" ]] || return 1
  [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" == "$expected_dir" ]] || return 1
  tr '\0' '\n' < "/proc/$pid/cmdline" | grep -Fqx -- "$expected_arg"
}

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

start_one() {
  local name="$1" port="$2" dir="$3" executable="$4" marker="$5"
  shift 5
  local pidfile="$RUN_DIR/$name.pid" pid
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if pid_matches "$name" "$pid" "$dir" "$marker"; then
      echo "$name already running (PID $pid)"
      return
    fi
    if [[ -d "/proc/$pid" ]]; then
      echo "$name PID file belongs to another process: $pidfile" >&2
      return 1
    fi
    rm "$pidfile"
  fi
  if ! port_free "$port"; then
    echo "$name port $port is occupied; refusing to start" >&2
    return 1
  fi
  (cd "$dir"; nohup setsid "$executable" "$@" >> "$LOG_DIR/$name.log" 2>&1 < /dev/null & echo $! > "$pidfile")
  pid="$(cat "$pidfile")"
  sleep 1
  if ! pid_matches "$name" "$pid" "$dir" "$marker"; then
    echo "$name did not start; see $LOG_DIR/$name.log" >&2
    return 1
  fi
  local ready=false path="/"
  [[ "$name" != backend ]] || path="/api/health"
  for _ in {1..60}; do
    if curl --noproxy '*' --silent --fail --max-time 1 "http://127.0.0.1:$port$path" > /dev/null; then
      ready=true
      break
    fi
    sleep 0.25
  done
  if [[ "$ready" != true ]]; then
    echo "$name process exists but HTTP is not ready; see $LOG_DIR/$name.log" >&2
    return 1
  fi
  echo "$name started (PID $pid, 127.0.0.1:$port)"
}

stop_one() {
  local name="$1" dir="$2" marker="$3" pidfile="$RUN_DIR/$1.pid" pid
  [[ -f "$pidfile" ]] || { echo "$name is not recorded as running"; return; }
  pid="$(cat "$pidfile")"
  if ! pid_matches "$name" "$pid" "$dir" "$marker"; then
    echo "$name PID $pid does not match this deployment; leaving it untouched" >&2
    return 1
  fi
  kill "$pid"
  for _ in {1..30}; do
    if ! pid_matches "$name" "$pid" "$dir" "$marker"; then break; fi
    sleep 0.2
  done
  if pid_matches "$name" "$pid" "$dir" "$marker"; then
    echo "$name PID $pid did not exit; leaving PID file for inspection" >&2
    return 1
  fi
  rm "$pidfile"
  echo "$name stopped"
}

case "${1:-}" in
  start)
    start_one backend "$BACKEND_PORT" "$ROOT/backend" "$ROOT/backend/.venv/bin/uvicorn" app.main:app app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
    start_one frontend "$FRONTEND_PORT" "$ROOT/frontend" "$(command -v node)" "$ROOT/frontend/node_modules/vite/bin/vite.js" "$ROOT/frontend/node_modules/vite/bin/vite.js" preview --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
    ;;
  stop)
    stop_one frontend "$ROOT/frontend" "$ROOT/frontend/node_modules/vite/bin/vite.js"
    stop_one backend "$ROOT/backend" app.main:app
    ;;
  status)
    for name in backend frontend; do
      if [[ "$name" == backend ]]; then dir="$ROOT/backend"; marker=app.main:app
      else dir="$ROOT/frontend"; marker="$ROOT/frontend/node_modules/vite/bin/vite.js"; fi
      if [[ -f "$RUN_DIR/$name.pid" ]]; then
        pid="$(cat "$RUN_DIR/$name.pid")"
        if pid_matches "$name" "$pid" "$dir" "$marker"; then echo "$name running (PID $pid)"
        else echo "$name stale PID file ($pid)"; fi
      else echo "$name stopped"; fi
    done
    ;;
  logs)
    tail -n 100 -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log"
    ;;
  *) echo "Usage: $0 {start|stop|status|logs}" >&2; exit 2 ;;
esac
