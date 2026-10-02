import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SALAD_API_KEY", "TEST_FAKE_KEY_NO_NETWORK")
os.environ.setdefault("R2_ACCESS_KEY_ID", "TEST_FAKE_R2_ID")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "TEST_FAKE_R2_SECRET")
os.environ.setdefault("R2_ENDPOINT_URL", "https://example.invalid")

spec = importlib.util.spec_from_file_location("deployer", ROOT / "salad-worker/deploy_salad.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
GPU_ID = "gpu-5090-test-id"


def correct_group():
    expected = d.group_payload(GPU_ID)
    return {
        **expected,
        "container": expected["container"].copy(),
        "pending_change": False,
        "version": 1,
    }


class MediumDeployTest(unittest.TestCase):
    def test_hardware_priority_and_scale_zero(self):
        group = d.group_payload(GPU_ID)
        self.assertEqual(d.QUEUE_NAME, "qwen-comfyui-medium")
        self.assertEqual(d.GROUP_NAME, "qwen-comfyui-fp8-medium")
        self.assertEqual(group["container"]["resources"], {
            "cpu": 4, "memory": 30720, "shm_size": 2048,
            "storage_amount": 107374182400, "gpu_classes": [GPU_ID],
        })
        self.assertEqual(group["container"]["priority"], "medium")
        self.assertEqual(group["replicas"], 0)
        self.assertEqual(group["queue_connection"], {
            "path": "/prompt", "port": 3000, "queue_name": "qwen-comfyui-medium"
        })
        self.assertEqual(group["queue_autoscaler"]["min_replicas"], 0)
        self.assertEqual(group["queue_autoscaler"]["max_replicas"], 1)

    def test_dry_run_does_not_write(self):
        with patch.object(d, "get_queue", return_value=None), \
             patch.object(d, "get_group", return_value=None), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=False)
            request.assert_not_called()

    def test_existing_correct_does_not_create_or_patch(self):
        group = correct_group()
        with patch.object(d, "get_queue", return_value={"name": d.QUEUE_NAME}), \
             patch.object(d, "get_group", return_value=group), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
            request.assert_not_called()

    def test_missing_queue_and_group_are_created_once(self):
        group = correct_group()
        with patch.object(d, "get_queue", side_effect=[None, None, {"name": d.QUEUE_NAME}, {"name": d.QUEUE_NAME}]), \
             patch.object(d, "get_group", side_effect=[None, None, group, group]), \
             patch.object(d, "request", return_value={}) as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
            self.assertEqual([c.args[0] for c in request.call_args_list], ["POST", "POST"])
            self.assertIn("/queues", request.call_args_list[0].args[1])
            self.assertIn("/containers", request.call_args_list[1].args[1])

    def test_existing_drift_is_repaired_without_deletion(self):
        wrong = correct_group()
        wrong["container"]["resources"] = {
            "cpu": 4, "memory": 16384, "shm_size": 2048,
            "storage_amount": 53687091200, "gpu_classes": ["gpu-4090"],
        }
        correct = correct_group()
        with patch.object(d, "get_queue", return_value={"name": d.QUEUE_NAME}), \
             patch.object(d, "get_group", side_effect=[wrong, wrong, wrong, correct]), \
             patch.object(d, "request", return_value={}) as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
            self.assertEqual([c.args[0] for c in request.call_args_list], ["PATCH"])
            patched = request.call_args_list[0].args[2]
            self.assertEqual(patched["container"]["resources"]["memory"], 30720)
            self.assertEqual(patched["container"]["resources"]["gpu_classes"], [GPU_ID])

    def test_wrong_queue_connection_is_rejected(self):
        wrong = correct_group()
        wrong["queue_connection"]["queue_name"] = "old-queue"
        with self.assertRaisesRegex(RuntimeError, "incompatible queue_connection"):
            d.assert_queue_connection(wrong)

    def test_single_priority_cli_enforced(self):
        with patch.object(sys, "argv", ["deploy_salad.py", "--priority", "high"]), \
             self.assertRaises(SystemExit) as result:
            d.main()
        self.assertEqual(result.exception.code, 2)

    def test_frontend_patcher_is_idempotent(self):
        # Test the exact original option block of frontend/src/App.jsx.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "frontend/src").mkdir(parents=True)
            script = root / "scripts/apply-medium-frontend.py"
            script.write_text((ROOT / "scripts/apply-medium-frontend.py").read_text())
            target = root / "frontend/src/App.jsx"
            target.write_text('''const PRIORITY_OPTIONS = [
  { value: "high", label: "High", help: "Highest availability, highest cost" },
  { value: "medium", label: "Medium — Default", help: "Balanced availability and cost" },
  { value: "low", label: "Low", help: "Lower cost, more interruptions" },
  { value: "batch", label: "Batch / Lowest", help: "Lowest cost; may wait for capacity" }
];\n''')
            for _ in range(2):
                subprocess.run([sys.executable, script], check=True, stdout=subprocess.DEVNULL)
            content = target.read_text()
            self.assertIn('value: "medium"', content)
            self.assertNotIn('value: "high"', content)
            self.assertNotIn('value: "batch"', content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
