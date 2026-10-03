"""Offline regression tests for opt-in Salad replica bootstrap (no API calls)."""
import copy
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for raw in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key] = value.strip().strip('"')
os.environ.update({
    "SALAD_API_KEY": "TEST_FAKE_KEY_NO_NETWORK",
    "R2_ACCESS_KEY_ID": "TEST_FAKE_R2_ID",
    "R2_SECRET_ACCESS_KEY": "TEST_FAKE_R2_SECRET",
    "R2_ENDPOINT_URL": "https://example.invalid",
})
spec = importlib.util.spec_from_file_location(
    "salad_bootstrap_under_test", ROOT / "salad-worker/deploy_salad.py"
)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
GPU = "test-gpu-id"


def group(replicas=0, status="deploying", pending=False):
    result = copy.deepcopy(d.group_payload(GPU, replicas=replicas))
    result.update({
        "pending_change": pending,
        "current_state": {"status": status, "instance_status_counts": {}},
    })
    return result


class BootstrapTests(unittest.TestCase):
    def test_default_create_stays_scale_to_zero(self):
        self.assertEqual(d.group_payload(GPU)["replicas"], 0)
        self.assertEqual(d.MIN_REPLICAS, 0)
        self.assertEqual(d.MAX_REPLICAS, 1)
        self.assertEqual(d.BOOTSTRAP_REPLICAS, 1)

    def test_normal_apply_does_not_wake_idle_existing_group(self):
        with patch.object(d, "get_queue", return_value=d.queue_payload()), \
             patch.object(d, "get_group", return_value=group()), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU, apply=True)
            request.assert_not_called()

    def test_bootstrap_existing_zero_uses_replicas_only_patch(self):
        idle = group(0)
        requested = group(1)
        with patch.object(d, "get_queue", return_value=d.queue_payload()), \
             patch.object(d, "get_group", side_effect=[idle, idle, idle, requested]), \
             patch.object(d, "request", return_value={}) as request, \
             redirect_stdout(io.StringIO()):
            d.report(GPU, apply=True, bootstrap=True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args, ("PATCH", d.group_path(), {"replicas": 1}))
        self.assertEqual(request.call_args.kwargs["content_type"], "application/merge-patch+json")

    def test_bootstrap_already_one_does_not_patch_or_restart(self):
        with patch.object(d, "get_queue", return_value=d.queue_payload()), \
             patch.object(d, "get_group", return_value=group(1)), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU, apply=True, bootstrap=True)
            request.assert_not_called()

    def test_first_create_with_bootstrap_requests_one_replica(self):
        one = group(1)
        with patch.object(d, "get_queue", return_value=d.queue_payload()), \
             patch.object(d, "get_group", side_effect=[None, None, one, one]), \
             patch.object(d, "request", return_value={}) as request, \
             redirect_stdout(io.StringIO()):
            d.report(GPU, apply=True, bootstrap=True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertEqual(request.call_args.args[2]["replicas"], 1)

    def test_stopped_group_is_started_on_explicit_bootstrap(self):
        with patch.object(d, "get_group", return_value=group(1, "deploying")), \
             patch.object(d, "request", return_value={}) as request, \
             redirect_stdout(io.StringIO()):
            d.bootstrap_group(group(1, "stopped"))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[:2], ("POST", d.group_path() + "/start"))

    def test_pending_change_is_never_overridden(self):
        with patch.object(d, "request") as request:
            with self.assertRaisesRegex(RuntimeError, "pending"):
                d.bootstrap_group(group(0, pending=True))
            request.assert_not_called()

    def test_bootstrap_without_apply_rejected_before_network(self):
        with patch.object(sys, "argv", ["deploy_salad.py", "--bootstrap"]), \
             patch.object(d, "select_gpu") as select_gpu, \
             redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as err:
            d.main()
        self.assertEqual(err.exception.code, 2)
        select_gpu.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
