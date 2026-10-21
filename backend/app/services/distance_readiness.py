"""Require an accepted real binary, not merely an installed executable."""
from pathlib import Path
import hashlib
import json
import os
from functools import lru_cache
from app.config import BACKEND_ROOT

CONTRACT_BLOCKER = '真实 Distance 需要与当前二进制匹配的小样本数值验收及完整 Surface 独立读回验收记录。'

@lru_cache(maxsize=8)
def _digest(path: str, size: int, mtime: int, ctime: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def distance_unavailable_reason() -> str:
    exe = Path(os.environ.get('ESDF_EXECUTABLE', BACKEND_ROOT / 'scripts/esdf_cpp/build/voxel_points_to_esdf'))
    if not exe.is_file() or not os.access(exe, os.X_OK):
        return f'未安装 Voxblox 转换器：{exe}；{CONTRACT_BLOCKER}'
    try:
        report = json.loads(Path(os.environ.get('ESDF_ACCEPTANCE_REPORT','')).read_text())
        for binary, key in [(exe,'executable_sha256'),(exe.with_name('verify_esdf_layer'),'reader_sha256')]:
            stat=binary.stat()
            if _digest(str(binary.resolve()),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=report[key]:
                return 'Distance 二进制已改变，需要重新执行真实验收'
        if report.get('accepted') is not True or report.get('native_numeric_accepted') is not True or report.get('real_surface_readback_accepted') is not True:
            return CONTRACT_BLOCKER
    except (OSError, ValueError, KeyError):
        return CONTRACT_BLOCKER
    return ''
