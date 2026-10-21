"""Readiness certificate predicates only; no executable/algorithm acceptance."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.services.distance_readiness import distance_unavailable_reason, distance_full_chain_accepted

class DistanceReadinessTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
  self.exe=root/'converter';self.exe.write_bytes(b'predicate-fixture-A');self.exe.chmod(0o755)
  self.reader=root/'verify_esdf_layer';self.reader.write_bytes(b'reader-predicate-fixture')
  self.report=root/'acceptance.json'
  self.env=patch.dict(os.environ,ESDF_EXECUTABLE=str(self.exe),ESDF_ACCEPTANCE_REPORT=str(self.report));self.env.start();self.addCleanup(self.env.stop)
 def certificate(self,**kwargs):
  d=dict(accepted=True,native_numeric_accepted=True,real_surface_readback_accepted=True,executable_sha256=hashlib.sha256(self.exe.read_bytes()).hexdigest(),reader_sha256=hashlib.sha256(self.reader.read_bytes()).hexdigest());d.update(kwargs);self.report.write_text(json.dumps(d))
 def test_installation_alone_is_blocked(self):self.assertTrue(distance_unavailable_reason())
 def test_numeric_without_real_surface_is_blocked(self):
  self.certificate(real_surface_readback_accepted=False);self.assertTrue(distance_unavailable_reason())
 def test_matching_certificate_allows_execution_without_claiming_full_chain(self):
  self.certificate();self.assertEqual(distance_unavailable_reason(),'');self.assertFalse(distance_full_chain_accepted())
 def test_same_length_rewrite_with_preserved_mtime_is_blocked(self):
  self.certificate();self.assertEqual(distance_unavailable_reason(),'');stat=self.exe.stat();self.exe.write_bytes(b'predicate-fixture-B');os.utime(self.exe,ns=(stat.st_atime_ns,stat.st_mtime_ns));self.assertTrue(distance_unavailable_reason())
 def test_reader_change_is_blocked(self):
  self.certificate();self.reader.write_bytes(b'changed reader');self.assertTrue(distance_unavailable_reason())
 def test_full_chain_needs_explicit_record_and_job(self):
  self.certificate(real_three_stage_accepted=True);self.assertFalse(distance_full_chain_accepted());self.certificate(real_three_stage_accepted=True,real_three_stage_job_id='predicate-test-job');self.assertTrue(distance_full_chain_accepted())
