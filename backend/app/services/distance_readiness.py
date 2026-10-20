"""Report installed dependencies separately from converter correctness."""
from pathlib import Path
import os
from app.config import BACKEND_ROOT

CONTRACT_BLOCKER = (
    "转换器契约未通过：投影 sdf 被直接用作 ESDF 种子；未知体素被标为 observed 并传播正距离，"
    "且首次入队即锁定，尚未保证最短距离。须修复并通过符号/未知区/距离测试。"
)


def distance_unavailable_reason() -> str:
    exe = Path(os.environ.get("ESDF_EXECUTABLE", BACKEND_ROOT / "scripts/esdf_cpp/build/voxel_points_to_esdf"))
    reasons = []
    if not exe.is_file() or not os.access(exe, os.X_OK):
        reasons.append(f"未安装 Voxblox 转换器：{exe}")
    reasons.append(CONTRACT_BLOCKER)
    return "；".join(reasons)
