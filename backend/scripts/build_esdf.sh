#!/usr/bin/env bash
# Preparation is cheap. Compilation is explicit, isolated, and serial.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ACTION="${1:---preflight}"
DISTANCE_ROOT="${DISTANCE_ROOT:-$ROOT/../envs/distance}"
VOXBLOX_WS="$DISTANCE_ROOT/ws"
export VOXBLOX_WS
case "$ACTION" in
  --fetch)
    python3 - "$ROOT/ops/distance-sources.lock.json" "$VOXBLOX_WS/src" <<'PY'
import json, subprocess, sys
from pathlib import Path
for name, item in json.loads(Path(sys.argv[1]).read_text()).items():
    dest=Path(sys.argv[2])/name
    if not dest.exists():
        dest.mkdir(parents=True)
        subprocess.run(['git','init',str(dest)],check=True)
        subprocess.run(['git','-C',str(dest),'remote','add','origin',item['url']],check=True)
        subprocess.run(['git','-C',str(dest),'fetch','--depth','1','origin',item['commit']],check=True)
        subprocess.run(['git','-C',str(dest),'checkout','--detach','FETCH_HEAD'],check=True)
    actual=subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()
    if actual!=item['commit'] or subprocess.check_output(['git','-C',str(dest),'status','--porcelain']):
        raise SystemExit(f'{dest}: source differs from lock; preserving it for inspection')
PY
    ;;
  --preflight)
    echo "Distance workspace: $VOXBLOX_WS"
    echo "ROS_VERSION=${ROS_VERSION:-unset} (ROS2 must not enter Distance build)"
    for tool in cmake g++ protoc catkin; do command -v "$tool" || true; done
    for pkg in libeigen3-dev libprotobuf-dev libgoogle-glog-dev libgflags-dev; do dpkg-query -W "$pkg" 2>/dev/null || true; done
    echo "No compile performed. Next: --fetch, then isolated --build in GPU mode."
    ;;
  --build)
    [[ "${ROS_VERSION:-}" != 2 ]] || { echo 'Refusing ROS2 build environment' >&2; exit 1; }
    LIMIT=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
    [[ "$LIMIT" == max || "$LIMIT" -ge 8589934592 ]] || { echo 'Compile deferred: cgroup memory below 8 GiB (build guard, not production sizing)' >&2; exit 1; }
    command -v catkin >/dev/null || { echo 'Install/activate isolated catkin tools first; see docs/deploy-distance.md' >&2; exit 1; }
    [[ -d "$VOXBLOX_WS/src/voxblox" ]] || { echo 'Run --fetch first' >&2; exit 1; }
    bash "$0" --fetch
    cd "$VOXBLOX_WS"
    catkin init
    catkin config --no-extend --install --cmake-args -DCMAKE_BUILD_TYPE=Release -DCATKIN_ENABLE_TESTING=ON -DUSE_SYSTEM_EIGEN=ON -DUSE_SYSTEM_GLOG=ON -DUSE_SYSTEM_GFLAGS=ON -DUSE_SYSTEM_PROTOBUF=ON -DPYTHON_EXECUTABLE="$(command -v python3)"
    catkin build voxblox -j1 -p1 --no-status
    cmake -S "$SCRIPT_DIR/esdf_cpp" -B "$DISTANCE_ROOT/converter-build" -DCMAKE_BUILD_TYPE=Release -DVOXBLOX_WS="$VOXBLOX_WS"
    cmake --build "$DISTANCE_ROOT/converter-build" --parallel 1
    echo "Built candidate: $DISTANCE_ROOT/converter-build/voxel_points_to_esdf; contract acceptance still required."
    ;;
  *) echo 'Usage: build_esdf.sh --preflight|--fetch|--build' >&2; exit 2 ;;
esac
