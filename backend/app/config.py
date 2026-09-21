"""Central path / constant configuration for the backend.

Nothing here is algorithm-specific: it only knows where the platform keeps
its jobs, demo assets and backend registry files.
"""
from __future__ import annotations

from pathlib import Path

# 3d-mapping-platform/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# backend/
BACKEND_ROOT = PROJECT_ROOT / "backend"

# backend/app/
APP_ROOT = Path(__file__).resolve().parent

JOBS_DIR = PROJECT_ROOT / "jobs"
DEMO_JOBS_DIR = PROJECT_ROOT / "demo_jobs"

# backend/config/backends/*.json  (pose / surface / distance)
BACKENDS_CONFIG_DIR = BACKEND_ROOT / "config" / "backends"

# Whether the first backend start seeds one completed demo job so the UI
# has immediate content and page-refresh state restoration can be shown.
SEED_DEMO_JOB_ON_START = True

STAGES = ["pose", "surface", "distance"]

STAGE_LABELS = {
    "pose": "Pose / SLAM",
    "surface": "Surface Mapping",
    "distance": "Distance Field / ESDF",
}

JOB_STATUSES = ["created", "running", "completed", "failed", "cancelled"]
STAGE_STATUSES = ["waiting", "running", "completed", "failed", "cancelled"]

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]