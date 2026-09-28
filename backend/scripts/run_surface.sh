#!/usr/bin/env bash
# Real Surface adapter. Job layout is stage1_pose/stage2_surface/stage3_esdf.
set -euo pipefail

usage() { echo "usage: $0 --job-dir DIR --backend ID --mode demo|full" >&2; exit 2; }

JOB_DIR=""; BACKEND=""; MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-dir) JOB_DIR="${2:?}"; shift 2 ;;
    --backend) BACKEND="${2:?}"; shift 2 ;;
    --mode) MODE="${2:?}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$JOB_DIR" && -n "$BACKEND" && -n "$MODE" ]] || usage
[[ "$MODE" == "demo" || "$MODE" == "full" ]] || usage

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
[[ -x "$PLATFORM_PYTHON" ]] || PLATFORM_PYTHON=python3
case "$BACKEND" in
  mrhash_lidar)
    exec "$PLATFORM_PYTHON" "$SCRIPT_DIR/mrhash_surface_adapter.py" --job-dir "$JOB_DIR" --mode "$MODE"
    ;;
  *)
    echo "No real Surface adapter is available for backend '$BACKEND'." >&2
    exit 2
    ;;
esac
