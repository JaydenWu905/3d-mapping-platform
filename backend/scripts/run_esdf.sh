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
[[ -n "$JOB_DIR" && -n "$BACKEND" && -n "$MODE" ]] || usage

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR="$JOB_DIR/stage3_esdf"
PREVIEW_DIR="$STAGE_DIR/preview"
mkdir -p "$PREVIEW_DIR"

# ---------- 1. 从 surface manifest 里找 voxel_points ----------
SURFACE_MANIFEST="$JOB_DIR/stage2_surface/result_manifest.json"
if [[ ! -f "$SURFACE_MANIFEST" ]]; then
  echo "[esdf] ERROR: 找不到 $SURFACE_MANIFEST" >&2
  exit 1
fi

# 用内嵌的 Python 从 JSON 里提取 artifact path
INPUT_PLY=$(python3 - "$SURFACE_MANIFEST" "$JOB_DIR/stage2_surface" <<'PY'
import json, sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
stage_dir = Path(sys.argv[2])
# 优先找 voxel_points，其次 navigation_input，再退到 surface_mesh
for wanted in ("voxel_points", "navigation_input", "surface_mesh"):
    for art in manifest.get("artifacts", []):
        if art.get("artifact_id") == wanted:
            print(stage_dir / art["path"])
            sys.exit(0)
PY
)

if [[ -z "$INPUT_PLY" || ! -f "$INPUT_PLY" ]]; then
  echo "[esdf] ERROR: surface 阶段没有可用的输入 PLY" >&2
  exit 1
fi
echo "[esdf] 输入 PLY: $INPUT_PLY"

# ---------- 2. 写 progress.json 的辅助函数 ----------
write_progress() {
  cat > "$STAGE_DIR/progress.json" <<EOF
{
  "stage": "distance",
  "backend": "$BACKEND",
  "status": "$1",
  "phase": "$2",
  "progress": $3,
  "current": 0,
  "total": 0,
  "unit": "",
  "message": "$4",
  "updated_at": "$(date +%Y-%m-%dT%H:%M:%S)"
}
EOF
}

write_progress "running" "esdf_generation" 10 "Running Voxblox ESDF"

# ---------- 3. 调用 C++ 程序 ----------
VOXBLOX_EXE="/home/voxblox/catkin_ws/devel/lib/voxblox_ground_truth/voxel_points_to_esdf"
if [[ ! -x "$VOXBLOX_EXE" ]]; then
  echo "[esdf] ERROR: 找不到 $VOXBLOX_EXE" >&2
  write_progress "failed" "missing_exe" 0 "C++ executable missing"
  exit 1
fi

set +e
"$VOXBLOX_EXE" \
  --input "$INPUT_PLY" \
  --output_dir "$STAGE_DIR" \
  --voxel_size 0.1 \
  --max_esdf_distance 2.5
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -ne 0 ]]; then
  write_progress "failed" "cxx_failed" 0 "Voxblox exit $EXIT_CODE"
  exit $EXIT_CODE
fi

# ---------- 4. 生成三张切片 PNG ----------
write_progress "running" "slice_rendering" 80 "Rendering slice PNGs"

PLATFORM_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
[[ -x "$PLATFORM_PYTHON" ]] || PLATFORM_PYTHON=python3

"$PLATFORM_PYTHON" "$SCRIPT_DIR/esdf_postprocess.py" \
  --input_ply "$STAGE_DIR/preview/esdf_vis.ply" \
  --output_dir "$PREVIEW_DIR" \
  --resolution 480

# ---------- 5. 写 result_manifest.json ----------
ESDF_SIZE=$(stat -c%s "$STAGE_DIR/map.esdf" 2>/dev/null || echo 0)
PLY_SIZE=$(stat -c%s "$STAGE_DIR/preview/esdf_vis.ply" 2>/dev/null || echo 0)

# 收集实际生成的切片（只有当 PNG 存在时才登记）
SLICE_ARTIFACTS=""
for plane in xy xz yz; do
  if [[ -f "$PREVIEW_DIR/slice_${plane}.png" ]]; then
    SLICE_ARTIFACTS="$SLICE_ARTIFACTS
    ,{\"artifact_id\": \"slice_${plane}\", \"role\": \"preview\", \"path\": \"preview/slice_${plane}.png\", \"content_type\": \"image/png\", \"download\": false}"
  fi
done

cat > "$STAGE_DIR/result_manifest.json" <<EOF
{
  "schema_version": "0.1",
  "job_id": "$(basename "$JOB_DIR")",
  "stage": "distance",
  "backend": "$BACKEND",
  "status": "completed",
  "frame_id": "world",
  "unit": "meter",
  "runtime_sec": 0.0,
  "metrics": {
    "resolution_m": 0.1,
    "esdf_size_bytes": $ESDF_SIZE,
    "vis_ply_size_bytes": $PLY_SIZE
  },
  "artifacts": [
    {
      "artifact_id": "esdf_map",
      "role": "data",
      "path": "map.esdf",
      "content_type": "application/octet-stream",
      "download": true
    },
    {
      "artifact_id": "esdf_vis_ply",
      "role": "preview",
      "path": "preview/esdf_vis.ply",
      "content_type": "application/octet-stream",
      "download": false
    }
    $SLICE_ARTIFACTS
  ],
  "backend_details": {
    "mock_backend": false,
    "algorithm": "Voxblox ESDF (Dijkstra wavefront)",
    "voxel_size_m": 0.1,
    "max_esdf_distance_m": 2.5
  }
}
EOF

write_progress "completed" "completed" 100 "Completed"
echo "[esdf] 完成"
