"""Regression tests for Salad SCAIL-2 thin-image Hugging Face model installer.

No real model downloads, GPU, cloud operations or large files are required.
"""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'scail2_model_installer_under_test',
    ROOT / 'salad-worker/scail2/download_models.py',
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class ModelInstallerRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'hub-cache'
        self.blobs = self.cache / 'blobs'
        self.snapshots = self.cache / 'snapshots' / 'commit-id'
        self.blobs.mkdir(parents=True)
        self.snapshots.mkdir(parents=True)
        self.blob = self.blobs / 'abc123'
        self.payload = b'SCAIL2-TEST-CONTENT' * 8000
        self.blob.write_bytes(self.payload)
        self.snapshot = self.snapshots / 'model.safetensors'
        self.snapshot.symlink_to(Path('../../blobs/abc123'))
        self.expected = hashlib.sha256(self.payload).hexdigest()
        self.catalog = self.root / 'models.json'
        self.entry = {'role': 'toy', 'repo': 'fake/repo', 'path': 'model.safetensors',
                      'destination': 'diffusion_models/model.safetensors', 'sha256': self.expected}
        self.catalog.write_text(json.dumps({'artifacts': [self.entry]}))
        self.models = self.root / 'models'
        self.target = self.models / 'diffusion_models/model.safetensors'
        self.patches = [patch.object(installer, 'CATALOG', self.catalog),
                        patch.object(installer, 'MODELS_ROOT', self.models),
                        patch.object(installer, 'hf_hub_download', return_value=str(self.snapshot))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_linux_snapshot_symlink_hardlink_regression(self):
        # Reproduce original bug: Linux os.link hardlinks the *symlink*.
        self.target.parent.mkdir(parents=True)
        os.link(self.snapshot, self.target)
        self.assertTrue(self.target.is_symlink())
        self.assertFalse(self.target.is_file())
        with self.assertRaises(FileNotFoundError):
            self.target.read_bytes()
        installer.download()
        self.assertTrue(self.target.is_file())
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(os.stat(self.target).st_ino, os.stat(self.blob).st_ino)

    def test_existing_good_model_avoids_redownload(self):
        installer.download()
        installer.hf_hub_download.reset_mock()
        installer.download()
        installer.hf_hub_download.assert_not_called()

    def test_existing_corrupted_regular_file_is_replaced(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'CORRUPTED' * 30000)
        installer.download()
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_wrong_upstream_hash_fails_closed(self):
        entry = dict(self.entry, sha256='0' * 64)
        self.catalog.write_text(json.dumps({'artifacts': [entry]}))
        with self.assertRaisesRegex(RuntimeError, 'Model digest mismatch'):
            installer.download()
        self.assertFalse(self.target.exists())

    def test_out_of_root_destination_rejected_before_download(self):
        entry = dict(self.entry, destination='../outside.safetensors')
        self.catalog.write_text(json.dumps({'artifacts': [entry]}))
        with self.assertRaisesRegex(ValueError, 'Unsafe model destination'):
            installer.download()
        installer.hf_hub_download.assert_not_called()

    def test_copy_fallback_for_cross_filesystem(self):
        with patch.object(installer.os, 'link', side_effect=OSError(errno.EXDEV, 'Cross-device link')):
            installer.download()
        self.assertTrue(self.target.is_file())
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertNotEqual(os.stat(self.target).st_ino, os.stat(self.blob).st_ino)

    def test_other_link_failures_are_not_silently_copied(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'PREVIOUS GOOD' * 9000)
        before = self.target.read_bytes()
        with patch.object(installer.os, 'link', side_effect=PermissionError(errno.EACCES, 'Denied')):
            with self.assertRaises(PermissionError):
                installer.download()
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse(list(self.target.parent.glob('.scail2-install-*')))

    def test_dangling_outside_symlink_is_replaced_not_followed(self):
        self.target.parent.mkdir(parents=True)
        outside = self.root / 'outside'
        self.target.symlink_to(outside)
        installer.download()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertFalse(outside.exists())


if __name__ == '__main__':
    unittest.main()
