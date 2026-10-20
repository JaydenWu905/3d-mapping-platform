"""Report installed dependencies separately from converter correctness."""
from pathlib import Path
import os
from app.config import BACKEND_ROOT

CONTRACT_BLOCKER = (
    "原生MrHash采样到Voxblox中心的重采样/聚合、TSDF→ESDF与未知区政策尚未确定；"
    "输入/队列/输出已有源码修复，但完整转换器尚未通过构建和真实距离场验收。"
)


def distance_unavailable_reason() -> str:
    exe = Path(os.environ.get("ESDF_EXECUTABLE", BACKEND_ROOT / "scripts/esdf_cpp/build/voxel_points_to_esdf"))
    reasons = []
    if not exe.is_file() or not os.access(exe, os.X_OK):
        reasons.append(f"未安装 Voxblox 转换器：{exe}")
    reasons.append(CONTRACT_BLOCKER)
    return "；".join(reasons)
