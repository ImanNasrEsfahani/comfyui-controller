import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'salad-worker' / 'model_parts.py'
spec = importlib.util.spec_from_file_location('model_parts', MODULE_PATH)
model_parts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model_parts)


class FakeResponse(io.BytesIO):
    def __init__(self, payload, first, last, total, *, status=206):
        super().__init__(payload)
        self.status = status
        self.headers = {'Content-Range': f'bytes {first}-{last}/{total}'}


class PartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parts_root = Path(self.temp.name) / 'parts'
        self.target_root = Path(self.temp.name) / 'models'
        self.payload = b'fp8-test-vector-!' * 5
        self.specs = {
            'fp8': {
                'url': 'https://example.invalid/fp8',
                'sha256': hashlib.sha256(self.payload).hexdigest(),
                'relative_target': 'diffusion_models/fp8.safetensors',
                'slots': 7,
            }
        }
        self.size = 17

    def get(self, request, timeout=180):
        self.assertEqual(request.headers['Accept-encoding'], 'identity')
        range_text = request.headers['Range']
        self.assertTrue(range_text.startswith('bytes='))
        start, end = map(int, range_text[6:].split('-'))
        self.assertLess(start, len(self.payload))
        end = min(end, len(self.payload) - 1)
        return FakeResponse(self.payload[start:end + 1], start, end, len(self.payload))

    def download_all(self):
        with patch.object(model_parts, 'urlopen', side_effect=self.get):
            for index in range(self.specs['fp8']['slots']):
                model_parts.download_chunk('fp8', index, self.parts_root, self.size, self.specs)

    def test_chunk_sizes_verify_and_restore(self):
        self.download_all()
        chunk_paths = model_parts.parts('fp8', self.parts_root, self.size, self.specs)
        self.assertEqual(len(chunk_paths), 5)
        self.assertTrue(all(p.stat().st_size <= self.size for p in chunk_paths))
        self.assertEqual(model_parts.verify('fp8', self.parts_root, self.size, self.specs), len(self.payload))
        path = model_parts.restore('fp8', self.parts_root, self.target_root, self.size, self.specs)
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(model_parts.restore('fp8', self.parts_root, self.target_root, self.size, self.specs), path)

    def test_corrupted_part_is_rejected(self):
        self.download_all()
        chunk = self.parts_root / 'fp8' / 'part-01'
        chunk.write_bytes(b'X' + chunk.read_bytes()[1:])
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            model_parts.verify('fp8', self.parts_root, self.size, self.specs)
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            model_parts.restore('fp8', self.parts_root, self.target_root, self.size, self.specs)

    def test_missing_part_is_rejected(self):
        self.download_all()
        (self.parts_root / 'fp8' / 'part-01').unlink()
        with self.assertRaises(FileNotFoundError):
            model_parts.verify('fp8', self.parts_root, self.size, self.specs)

    def test_server_ignoring_range_is_rejected(self):
        def broken_response(request, timeout=180):
            return FakeResponse(self.payload, 0, len(self.payload) - 1, len(self.payload), status=200)
        with patch.object(model_parts, 'urlopen', side_effect=broken_response):
            with self.assertRaisesRegex(ValueError, 'did not honor HTTP Range'):
                model_parts.download_chunk('fp8', 0, self.parts_root, self.size, self.specs)

    def test_too_many_bytes_fails_before_download(self):
        self.specs['fp8']['slots'] = 1
        with patch.object(model_parts, 'urlopen', side_effect=self.get):
            with self.assertRaisesRegex(ValueError, 'exceed'):
                model_parts.download_chunk('fp8', 0, self.parts_root, self.size, self.specs)


if __name__ == '__main__':
    unittest.main()
