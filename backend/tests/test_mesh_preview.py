from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh

from app.services.mesh_preview import (
    atomic_replace_preview,
    build_preview_glb,
    validate_preview_glb,
)


class MeshPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_welds_exact_duplicates_and_builds_valid_glb(self) -> None:
        # Two adjacent triangles use duplicate indices for their shared edge,
        # matching the topology pattern in MrHash's marching-cubes PLY.
        vertices = np.array([
            [0, 0, 0], [1, 0, 0], [0, 1, 0],
            [1, 0, 0], [1, 1, 0], [0, 1, 0],
        ], dtype=float)
        mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [3, 4, 5]], process=False)
        source = self.root / "source.ply"
        source.write_bytes(trimesh.exchange.ply.export_ply(mesh, encoding="ascii"))
        output = self.root / "preview.glb"

        metrics = build_preview_glb(source, output, target_faces=2)

        self.assertEqual(metrics["preview_source_vertices"], 6)
        self.assertEqual(metrics["preview_welded_vertices"], 4)
        self.assertEqual(metrics["preview_faces"], 2)
        self.assertEqual(validate_preview_glb(output)["faces"], 2)

    def test_atomic_replace_restores_old_preview_when_manifest_write_fails(self) -> None:
        destination = self.root / "surface_model.glb"
        candidate = self.root / ".candidate.glb"
        manifest = self.root / "result_manifest.json"
        destination.write_bytes(b"old-preview")
        candidate.write_bytes(b"new-preview")
        manifest.write_text(json.dumps({"status": "completed"}))

        with patch("app.services.mesh_preview._atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                atomic_replace_preview(candidate, destination, manifest, {"status": "completed"})

        self.assertEqual(destination.read_bytes(), b"old-preview")
        self.assertEqual(json.loads(manifest.read_text())["status"], "completed")


if __name__ == "__main__":
    unittest.main()
