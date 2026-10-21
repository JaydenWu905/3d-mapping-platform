#!/usr/bin/env bash
# 真实 Distance/ESDF 适配器 —— 调用 Voxblox C++ 程序。
# 契约：run_esdf.sh --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
set -euo pipefail

usage() { echo "usage: $0 --job-dir DIR --backend ID --mode demo|full" >&2; exit 2; }

JOB_DIR=""; BACKEND=""; MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-dir)  JOB_DIR="${2:?}";  shift 2 ;;
    --backend)  BACKEND="${2:?}"; shift 2 ;;
    --mode)     MODE="${2:?}";    shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$JOB_DIR" && "$BACKEND" == "voxel_esdf" && ( "$MODE" == "demo" || "$MODE" == "full" ) ]] || usage

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
unset OMP_NUM_THREADS OPENBLAS_NUM_THREADS
export PYTHONPATH="$SCRIPT_DIR/.."
exec "$PLATFORM_PYTHON" "$SCRIPT_DIR/distance_run.py" --job-dir "$JOB_DIR"
