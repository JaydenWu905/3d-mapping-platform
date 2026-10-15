#!/usr/bin/env bash
# Explicit stand-alone GLIM/bridge child launcher for GPU-mode verification.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/ops/glim-runtime.env"
set +u
source "$GLIM_ROS_SETUP"
set -u
export LD_LIBRARY_PATH="$GLIM_LD_LIBRARY_PATH:${LD_LIBRARY_PATH:-}"
unset OMP_NUM_THREADS
WORKSPACE="$(cd "$ROOT/.." && pwd)"
CONFIG_DIR="$WORKSPACE/$GLIM_CONFIG_PATH"
BRIDGE_PYTHON="$WORKSPACE/$GLIM_ROSBAGS_PYTHON"
case "${1:-}" in
  node)
    shift
    exec "$GLIM_NODE_COMMAND" --ros-args -p "config_path:=$CONFIG_DIR" -p dump_on_unload:=true "$@"
    ;;
  bridge)
    shift
    exec "$BRIDGE_PYTHON" "$ROOT/backend/scripts/glim_ros1_bridge.py" "$@"
    ;;
  *)
    echo "Usage: $0 {node|bridge} [arguments]" >&2
    exit 2
    ;;
esac
