"""Manifest-driven artifact resolution with hard path-traversal guard.

Security contract (from spec 二十、安全边界):
  * NO arbitrary file path downloads — no `GET /download?path=...`.
  * Every artifact must be listed in the stage's result_manifest.json.
  * Download: artifact must have `download: true`.
  * Every resolved path must stay inside the current job/stage directory
    (resolve() + is_relative_to containment, plus a canonical-parents check
    so a symlink pointing outside cannot escape the stage dir).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.manifest import load_manifest


class ArtifactNotFoundError(Exception):
    """Artifact id missing from manifest, or file missing on disk."""


class ArtifactNotDownloadableError(Exception):
    """Artifact exists in manifest but is not marked download=true."""


class PathTraversalError(Exception):
    """Resolved path escaped the stage directory (rejected)."""


@dataclass
class ArtifactFile:
    path: Path
    artifact_id: str
    role: str
    content_type: str
    preview_role: bool
    downloadable: bool
    manifest: dict


class ArtifactService:
    def __init__(self, job_service):
        self._jobs = job_service

    # ------------------------------------------------------------- resolution
    def resolve(self, job_id: str, stage: str, artifact_id: str) -> ArtifactFile:
        """Resolve artifact_id inside the stage dir, following manifest only."""
        stage_dir = self._stage_dir_checked(job_id, stage)
        manifest = load_manifest(stage_dir) or {}
        artifacts = manifest.get("artifacts", [])
        item = next((a for a in artifacts if a.get("artifact_id") == artifact_id), None)
        if item is None:
            raise ArtifactNotFoundError(
                f"artifact '{artifact_id}' not listed in the stage manifest "
                + "(only manifest-listed artifacts are accessible)"
            )
        return self._resolve_item(stage_dir, stage, item, manifest)

    def resolve_preview(self, job_id: str, stage: str, artifact_id: str) -> ArtifactFile:
        """Resolve an artifact for the in-page viewer (must be role 'preview')."""
        stage_dir = self._stage_dir_checked(job_id, stage)
        manifest = load_manifest(stage_dir) or {}
        item = next(
            (a for a in manifest.get("artifacts", []) if a.get("artifact_id") == artifact_id),
            None,
        )
        if item is None:
            raise ArtifactNotFoundError(f"preview '{artifact_id}' not listed in the stage manifest")
        if item.get("role") != "preview":
            raise ArtifactNotDownloadableError(f"artifact '{artifact_id}' is not a preview asset")
        return self._resolve_item(stage_dir, stage, item, manifest)

    # ---------------------------------------------------------------- helpers
    def _stage_dir_checked(self, job_id: str, stage: str) -> Path:
        # job_service.stage_dir already anchors under jobs/<safe_job_id>/;
        # _safe_job_id rejects '/', '\\', '..'.
        return self._jobs.stage_dir(job_id, stage)

    def _resolve_item(
        self, stage_dir: Path, stage: str, item: dict, manifest: dict
    ) -> ArtifactFile:
        rel = item.get("path")
        if not isinstance(rel, str) or not rel:
            raise ArtifactNotFoundError("artifact entry has no path")
        base = stage_dir.resolve()
        target = (base / rel).resolve()

        # Containment: resolved target must live inside the stage dir.
        if not _contained(base, target):
            raise PathTraversalError(
                f"artifact path '{rel}' escapes the stage directory; download rejected"
            )
        if not target.is_file():
            raise ArtifactNotFoundError(f"artifact file '{rel}' is missing on disk")

        return ArtifactFile(
            path=target,
            artifact_id=item.get("artifact_id", ""),
            role=item.get("role", ""),
            content_type=item.get("content_type", "application/octet-stream"),
            preview_role=(item.get("role") == "preview"),
            downloadable=bool(item.get("download") is True),
            manifest=manifest,
        )


def _contained(base: Path, target: Path) -> bool:
    """True when target is base or below it, treating symlinks canonically."""
    try:
        if base not in target.parents and target != base:
            return False
    except TypeError:  # pragma: no cover
        return False
    # Re-check each component canonically so a symlink cannot escape.
    try:
        resolved = target.resolve()
    except OSError:
        return False
    if resolved != target:
        return _contained(base.resolve(), resolved)
    return True
