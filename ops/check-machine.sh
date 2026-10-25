#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
printf 'platform=%s\n' "$(git rev-parse HEAD)"
for tool in python3.12 node npm cmake g++ protoc nvidia-smi; do
  command -v "$tool" || printf 'MISSING %s\n' "$tool"
done
python3.12 --version 2>&1 || true
node --version 2>&1 || true
npm --version 2>&1 || true
printf 'memory.max=%s\n' "$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo unknown)"
if command -v nvidia-smi >/dev/null; then nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader; fi
for path in ops/glim-runtime.env ops/device_runtime.json /opt/ros/humble/setup.bash backend/.venv/bin/python frontend/node_modules/.bin/vite; do
  [[ -e "$path" ]] && printf 'OK %s\n' "$path" || printf 'MISSING %s\n' "$path"
done
for pkg in ros-humble-glim-ros-cuda12.6 ros-humble-ros-base libgtsam-notbb-dev libgtsam-points-cuda12.6-dev libgoogle-glog-dev libgflags-dev; do
  dpkg-query -W -f='${Package} ${Version}\n' "$pkg" 2>/dev/null || printf 'MISSING %s\n' "$pkg"
done
if [[ -f ops/glim-runtime.env ]]; then
  source ops/glim-runtime.env
  if [[ -n "${MRHASH_ROOT:-}" && -d "${MRHASH_ROOT:-}/.git" ]]; then
    printf 'mrhash=%s\n' "$(git -C "$MRHASH_ROOT" rev-parse HEAD)"
    git -C "$MRHASH_ROOT" submodule status
  else printf 'MISSING MRHASH_ROOT checkout\n'; fi
fi
bash backend/scripts/build_esdf.sh --preflight
