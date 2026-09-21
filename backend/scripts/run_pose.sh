#!/usr/bin/env bash
# Phase 2 适配器骨架 — Pose/SLAM 阶段（GLIM / fast_livo2 / lio_sam 等）。
#
# Phase 1 尚未接入本脚本：当前阶段由后端内置 MockRunner 演示，此文件仅
# 定义 Phase 2 真实算法的统一 CLI 契约（占位），执行后立即退出 1 以表明
# 该算法链路尚未实现——绝不把未实现的功能伪装成已完成。
#
# 契约（与 run_surface.sh / run_esdf.sh 一致）：
#   run_pose.sh --job-dir <JOB_DIR> --backend <backend_id> --mode demo|full
#
# 职责：
#   1. 读取上一阶段产物/输入数据（由调度器传入或按约定读取）；
#   2. 写进度：  <job_dir>/pose/progress.json
#                {"phase","progress","current","total","unit","message"}
#   3. 写产物：  <job_dir>/pose/preview/... 与 <job_dir>/pose/data/...
#   4. 登记 manifest：<job_dir>/pose/result_manifest.json
#                （artifacts: artifact_id / role / content_type / download + metrics）
#   5. 退出码： 0=成功，非 0=失败（调度器停止下游阶段）。
#
# 后端代码本身绝不 import 任何算法 Python 包；算法环境（Conda/容器等）
# 由本脚本自备，与平台隔离。
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

echo "[pose] Phase 2 真实算法尚未接入（backend=$BACKEND mode=$MODE job=$JOB_DIR）。"
exit 1