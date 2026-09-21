"""Unified progress.json model + atomic file I/O helpers."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON via temp file + atomic rename so readers never see half a file.

    uid suffix guards against concurrent writers within the same second.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Optional[Any] = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


def default_progress(stage: str, backend: str, status: str = "waiting") -> dict[str, Any]:
    return {
        "stage": stage,
        "backend": backend,
        "status": status,
        "phase": "",
        "progress": 0.0,
        "current": 0,
        "total": 0,
        "unit": "",
        "message": "",
        "elapsed_sec": 0.0,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_progress(stage_dir: Path, stage: str, backend: str) -> dict[str, Any]:
    """Read stage progress.json, fall back to a sensible default."""
    prog = read_json(stage_dir / "progress.json", None)
    if not isinstance(prog, dict):
        prog = default_progress(stage, backend)
    # Always reflect the current stage/backend; stale files must not mislabel.
    prog["stage"] = stage
    prog["backend"] = backend
    prog.setdefault("status", "waiting")
    prog.setdefault("phase", "")
    prog.setdefault("progress", 0.0)
    prog.setdefault("message", "")
    prog.setdefault("elapsed_sec", 0.0)
    return prog