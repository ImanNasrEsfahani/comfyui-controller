"""Keep SCAIL-2 GHCR worker releases pin-able by commit SHA."""
from pathlib import Path
import unittest


class GHCRImageTagTest(unittest.TestCase):
    def test_thin_has_latest_and_immutable_tag(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / '.github/workflows/build-scail2-worker.yml').read_text()
        self.assertIn('comfyui-controller-scail2-worker:thin\n', text)
        self.assertIn('comfyui-controller-scail2-worker:thin-${{ github.sha }}', text)
        self.assertIn("'salad-worker/scail2/**'", text)


if __name__ == '__main__':
    unittest.main()
