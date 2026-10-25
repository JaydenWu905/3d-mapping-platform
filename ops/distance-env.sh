#!/usr/bin/env bash
# Isolated catkin toolchain; never source ROS1/ROS2 into the platform shell.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${DISTANCE_TOOLS:-$ROOT/../envs/distance-tools}"
[[ -x "$TOOLS/bin/python3" ]] || { echo "Missing isolated tools: $TOOLS" >&2; exit 1; }
exec env -i HOME="$HOME" LANG=C.UTF-8 PATH="$TOOLS/bin:/usr/local/bin:/usr/bin:/bin" \
  PYTHONNOUSERSITE=1 DISTANCE_ROOT="${DISTANCE_ROOT:-$ROOT/../envs/distance}" \
  "$@"
