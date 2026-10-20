"""Synthetic contract checks only: these never execute Voxblox or validate ESDF."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('distance_input', Path(__file__).parents[1] / 'scripts/distance_input.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DistanceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name) / 'synthetic_job'
        self.stage = self.job / 'stage2_surface'
        self.stage.mkdir(parents=True)
        (self.stage / 'run.cfg').write_text('map:\n  virtual_voxel_size: 0.05\n')
        self.manifest = dict(job_id=self.job.name,status='completed',unit='meter',frame_id='world',
            backend_details={'mock_backend':False},artifacts=[
                dict(artifact_id='voxel_points',path='points.ply'),dict(artifact_id='run_config',path='run.cfg')])
        self.write_manifest()
        self.write_ply()

    def write_manifest(self):
        (self.stage / 'result_manifest.json').write_text(json.dumps(self.manifest))

    def write_ply(self, sdf=0.2, weight=2):
        header='ply\nformat binary_little_endian 1.0\nelement vertex 1\n'+'\n'.join(m.PROPERTIES)+'\nend_header\n'
        (self.stage / 'points.ply').write_bytes(header.encode()+struct.pack('<5f4B',0,0,0,sdf,weight,255,0,0,0))

    def test_inspect_preserves_resolution_and_marks_unknown_grid(self):
        d=m.inspect(self.job,scan=True)
        self.assertEqual(d['virtual_voxel_size_m'],0.05)
        self.assertEqual(d['surviving_weight_ge_2'],1)
        self.assertFalse(d['grid_ready'])

    def test_no_mesh_fallback(self):
        self.manifest['artifacts'][0]['artifact_id']='surface_mesh';self.write_manifest()
        with self.assertRaisesRegex(ValueError,'Mesh'):m.inspect(self.job)

    def test_truncated_and_nonfinite_rejected(self):
        self.write_ply(sdf=float('nan'))
        with self.assertRaisesRegex(ValueError,'Nonfinite'):m.inspect(self.job,scan=True)
        p=self.stage/'points.ply';p.write_bytes(p.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError,'truncated'):m.inspect(self.job)

    def test_unknown_and_low_weight_rejected(self):
        self.write_ply(weight=0)
        with self.assertRaisesRegex(ValueError,'invalid'):m.inspect(self.job,scan=True)
        self.write_ply(weight=1)
        with self.assertRaisesRegex(ValueError,'survive'):m.inspect(self.job,scan=True)

    def test_cross_job_mock_and_path_escape_rejected(self):
        for key,value in [('job_id','other_job'),('unit','cm')]:
            old=self.manifest[key];self.manifest[key]=value;self.write_manifest()
            with self.assertRaises(ValueError):m.inspect(self.job)
            self.manifest[key]=old
        self.manifest['backend_details']['mock_backend']=True;self.write_manifest()
        with self.assertRaisesRegex(ValueError,'non-mock'):m.inspect(self.job)
        self.manifest['backend_details']['mock_backend']=False
        self.manifest['artifacts'][0]['path']='../outside.ply';self.write_manifest()
        with self.assertRaisesRegex(ValueError,'Invalid'):m.inspect(self.job)


if __name__ == '__main__':unittest.main()
