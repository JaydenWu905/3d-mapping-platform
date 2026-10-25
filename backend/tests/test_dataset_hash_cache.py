import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.services.dataset_service import _sha256, _hash_file_version, DatasetService, DatasetDefinition


class HashCacheTests(unittest.TestCase):
    def test_one_file_version_is_hashed_once_and_write_invalidates_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.bag';p.write_bytes(b'old')
            _hash_file_version.cache_clear()
            with patch('app.services.dataset_service._version_stable',return_value=True):
                self.assertEqual(_sha256(p),hashlib.sha256(b'old').hexdigest())
                with patch.object(Path,'open',side_effect=AssertionError('unnecessary reread')):
                    self.assertEqual(_sha256(p),hashlib.sha256(b'old').hexdigest())
            p.write_bytes(b'new')
            self.assertEqual(_sha256(p),hashlib.sha256(b'new').hexdigest())

    def test_validation_cache_rechecks_changed_input_and_registry(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.bag';p.write_bytes(b'old')
            ds=DatasetDefinition(id='test',name='test',description='',kind='external',execution='real',
                input_manifest={},source_dir=Path(tmp),files={'bag':'input.bag'},pose={},runtime={},
                surface={},integrity={},rgbd={})
            service=DatasetService()
            with patch.object(DatasetDefinition,'validate',return_value=[]) as validate, patch('app.services.dataset_service._version_stable',return_value=True):
                service.validation_errors(ds);service.validation_errors(ds)
                self.assertEqual(validate.call_count,1)
                p.write_bytes(b'new content')
                service.validation_errors(ds)
                self.assertEqual(validate.call_count,2)
                service.validation_errors(replace(ds,integrity={'bag_sha256':'changed'}))
                self.assertEqual(validate.call_count,3)

    def test_fresh_same_size_rewrite_never_uses_hash_or_validation_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'input.bag';p.write_bytes(b'old')
            self.assertEqual(_sha256(p),hashlib.sha256(b'old').hexdigest())
            p.write_bytes(b'new')
            self.assertEqual(_sha256(p),hashlib.sha256(b'new').hexdigest())
