"""Offline regression tests: NO real Salad API requests or paid GPU usage."""
import importlib.util
import io
import os
import sys
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for raw in (ROOT / ".env.example").read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key] = value.strip().strip('"')
os.environ["SALAD_API_KEY"] = "TEST_FAKE_KEY_NO_NETWORK"
os.environ["R2_ACCESS_KEY_ID"] = "TEST_FAKE_R2_ID"
os.environ["R2_SECRET_ACCESS_KEY"] = "TEST_FAKE_R2_SECRET"
os.environ["R2_ENDPOINT_URL"] = "https://example.invalid"

spec = importlib.util.spec_from_file_location("salad_deployer", ROOT / "salad-worker/deploy_salad.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
GPU_ID = "test-5090-class-id"


def group():
    return {**d.group_payload(GPU_ID), "pending_change": False, "version": 1}


def queue():
    return d.queue_payload()


class EnvironmentOnlyDeploymentTests(unittest.TestCase):
    def test_all_hardware_and_names_come_from_env(self):
        payload = group()
        self.assertEqual(d.GROUP_NAME, os.environ["SALAD_CONTAINER_GROUP_NAME"])
        self.assertEqual(d.QUEUE_NAME, os.environ["SALAD_QUEUE_NAME"])
        self.assertEqual(payload["container"]["resources"], {
            "cpu": 4, "memory": 30720, "shm_size": 2048,
            "storage_amount": 107374182400, "gpu_classes": [GPU_ID],
        })
        self.assertEqual(payload["replicas"], 0)
        self.assertEqual(payload["container"]["priority"], os.environ["SALAD_PRIORITY"])
        self.assertEqual(payload["queue_connection"]["queue_name"], d.QUEUE_NAME)
        self.assertEqual(payload["queue_autoscaler"]["max_replicas"], 1)

    def test_name_is_not_hardcoded_in_deployer(self):
        content = (ROOT / "salad-worker/deploy_salad.py").read_text()
        self.assertNotIn("qwen-comfyui-fp8-medium", content)
        self.assertNotIn("qwen-comfyui-5090-medium", content)
        self.assertNotIn("qwen-comfyui-medium", content)

    def test_read_only_does_not_post_or_patch(self):
        with patch.object(d, "get_queue", return_value=None), \
             patch.object(d, "get_group", return_value=None), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=False)
            request.assert_not_called()

    def test_existing_correct_resource_not_recreated(self):
        with patch.object(d, "get_queue", return_value=queue()), \
             patch.object(d, "get_group", return_value=group()), \
             patch.object(d, "request") as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
            request.assert_not_called()

    def test_create_missing_queue_and_group(self):
        with patch.object(d, "get_queue", side_effect=[None, None, queue(), queue()]), \
             patch.object(d, "get_group", side_effect=[None, None, group(), group()]), \
             patch.object(d, "request", return_value={}) as request, redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
            methods = [call.args[0] for call in request.call_args_list]
            self.assertEqual(methods, ["POST", "POST"])
            self.assertIn("/queues", request.call_args_list[0].args[1])
            self.assertIn("/containers", request.call_args_list[1].args[1])

    def test_name_conflict_retries_creation_not_only_get(self):
        attempts = []
        def fake_request(method, path, body, **kwargs):
            attempts.append(method)
            if len(attempts) == 1:
                raise RuntimeError("POST -> HTTP 409: name_conflict")
            return {}
        with patch.object(d, "get_group", side_effect=[None, None, None, group()]), \
             patch.object(d, "request", side_effect=fake_request), \
             patch.object(d.time, "sleep"), redirect_stdout(io.StringIO()):
            d.ensure_group(GPU_ID)
        self.assertEqual(attempts, ["POST", "POST"])

    def test_reserved_name_aborts_boundedly(self):
        with patch.object(d, "get_group", return_value=None), \
             patch.object(d, "request", side_effect=RuntimeError("HTTP 409: name_conflict")), \
             patch.object(d.time, "monotonic", side_effect=[0, 1, 3]), \
             patch.object(d.time, "sleep"), patch.object(d, "SETTLE_TIMEOUT", 2), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "remained unavailable"):
                d.ensure_group(GPU_ID)

    def test_group_with_wrong_queue_is_rejected(self):
        wrong = group()
        wrong["queue_connection"]["queue_name"] = "some-other-queue"
        with self.assertRaisesRegex(RuntimeError, "incompatible queue_connection"):
            d.assert_queue_connection(wrong)

    def test_drift_is_reconciled_without_delete(self):
        wrong = group()
        wrong["container"]["resources"]["memory"] = 16384
        with patch.object(d, "get_queue", return_value=queue()), \
             patch.object(d, "get_group", side_effect=[wrong, wrong, wrong, group()]), \
             patch.object(d, "request", return_value={}) as request, \
             redirect_stdout(io.StringIO()):
            d.report(GPU_ID, apply=True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], "PATCH")
        self.assertEqual(request.call_args.args[2]["container"]["resources"]["memory"], 30720)

    def test_invalid_priority_cli_rejected(self):
        with patch.object(sys, "argv", ["deploy_salad.py", "--priority", "high"]), \
             self.assertRaises(SystemExit) as result, redirect_stdout(io.StringIO()):
            d.main()
        self.assertEqual(result.exception.code, 2)

    def test_frontend_and_db_migration_idempotent(self):
        frontend = '''const PRIORITY_OPTIONS = [
  { value: "high", label: "High", help: "Highest availability, highest cost" },
  { value: "medium", label: "Medium — Default", help: "Balanced availability and cost" },
  { value: "low", label: "Low", help: "Lower cost, more interruptions" },
  { value: "batch", label: "Batch / Lowest", help: "Lowest cost; may wait for capacity" }
];

  const [priority, setPriority] = useState("medium");
  const priorityHelp = useMemo(
    () => PRIORITY_OPTIONS.find(p => p.value === priority)?.help || "",
    [priority]
  );

  useEffect(() => {
    refreshWorkflows().catch(e => setMessage(e.message));
          <label>GPU priority for this run</label>
          <select value={priority} onChange={e => setPriority(e.target.value)}>
            {PRIORITY_OPTIONS.map(item => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>

          <p className="hint">{priorityHelp}</p>
          disabled={busy || Boolean(uploadingKey) || !selected || missingImages.length > 0}
          {jobs.map(j => <Job key={j.id} job={j} />)}
function Job({ job }) {
  <div>{job.priority || "medium"}</div>
}
'''
        original_db = '''c.execute("ALTER TABLE jobs ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'")
def create_job(local_id, workflow_id, request_payload, *, priority="medium", salad_queue=None):
    now = utcnow()
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "frontend/src").mkdir(parents=True)
            (root / "backend/app").mkdir(parents=True)
            (root / "scripts/apply-env-source.py").write_text(
                (ROOT / "scripts/apply-env-source.py").read_text()
            )
            f = root / "frontend/src/App.jsx"
            db_file = root / "backend/app/db.py"
            f.write_text(frontend)
            db_file.write_text(original_db)
            for _ in range(2):
                subprocess.run([sys.executable, root / "scripts/apply-env-source.py"],
                               capture_output=True, check=True)
            self.assertIn('fetch("/health")', f.read_text())
            self.assertNotIn("PRIORITY_OPTIONS", f.read_text())
            self.assertIn("settings.salad_priority", db_file.read_text())
            self.assertNotIn("DEFAULT 'medium'", db_file.read_text())

    def test_sync_env_preserves_existing_secrets_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts/sync-env.py").write_text(
                (ROOT / "scripts/sync-env.py").read_text()
            )
            (root / ".env.example").write_text(
                "SALAD_API_KEY=\nSALAD_QUEUE_NAME=example-queue\n"
                "SALAD_CONTAINER_GROUP_NAME=new-group\n"
            )
            target = root / ".env"
            target.write_text("SALAD_API_KEY=SECRET_DO_NOT_OVERWRITE\nSALAD_QUEUE_NAME=existing-queue\n")
            result = subprocess.run(
                [sys.executable, root / "scripts/sync-env.py"],
                capture_output=True, text=True, check=True,
                env={**os.environ, "HOME": str(root)},
            )
            content = target.read_text()
            self.assertIn("SALAD_API_KEY=SECRET_DO_NOT_OVERWRITE", content)
            self.assertIn("SALAD_QUEUE_NAME=existing-queue", content)
            self.assertIn("SALAD_CONTAINER_GROUP_NAME=new-group", content)
            self.assertNotIn("SECRET_DO_NOT_OVERWRITE", result.stdout)
            self.assertEqual(len(list(root.glob(".comfyui-controller.env.backup-*"))), 1)

    def test_backend_reads_exact_queue_from_env(self):
        sys.path.insert(0, str(ROOT / "backend"))
        from app.config import settings
        from app import salad
        self.assertEqual(settings.salad_queue_name(), os.environ["SALAD_QUEUE_NAME"])
        self.assertEqual(salad.queue_name_for_priority(None), os.environ["SALAD_QUEUE_NAME"])
        with self.assertRaises(ValueError):
            salad.queue_name_for_priority("high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
