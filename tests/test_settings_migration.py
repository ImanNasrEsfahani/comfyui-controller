"""Offline safety tests: no Salad, R2 or GitHub traffic."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TEST_ENV = {
    "APP_NAME": "test-controller", "DB_PATH": "/tmp/controller-settings-test.db",
    "MAX_UPLOAD_MB": "100", "APP_INTERNAL_TOKEN": "TEST_ADMIN_TOKEN",
    "SALAD_API_KEY": "TEST_SALAD_KEY", "SALAD_API_BASE_URL": "https://example.invalid",
    "SALAD_USER_AGENT": "test", "SALAD_HTTP_TIMEOUT_SECONDS": "3",
    "SALAD_ORG": "test-org", "SALAD_PROJECT": "test-project",
    "SALAD_QUEUE_NAME": "test-queue", "SALAD_QUEUE_DISPLAY_NAME": "Test Queue",
    "SALAD_PRIORITY": "medium", "SALAD_GPU_NAME": "RTX 5090 (32 GB)",
    "SALAD_LEGACY_QUEUE": "legacy", "R2_ENDPOINT_URL": "https://example.invalid",
    "R2_BUCKET": "test-bucket", "R2_ACCESS_KEY_ID": "TEST_ACCESS",
    "R2_SECRET_ACCESS_KEY": "TEST_SECRET", "R2_REGION": "auto",
    "R2_PRESIGN_TTL_SECONDS": "3600", "SALAD_IMAGE": "ghcr.io/test/worker:v1",
    "SALAD_CONTAINER_GROUP_NAME": "test-group-v1",
    "SALAD_CONTAINER_GROUP_DISPLAY_NAME": "Test Group V1",
    "DIRECT_QUEUE_ENABLED": "false",
}

# The standalone ZIP may be tested without all unchanged repository files.
# In the real repository, import the actual queue client as usual.
if not (ROOT / "backend/app/salad.py").exists():
    import types
    salad_stub = types.ModuleType("app.salad")
    salad_stub.headers = lambda: {}
    sys.modules["app.salad"] = salad_stub
with patch.dict(os.environ, TEST_ENV):
    from app import db, settings_store, salad_control
    from app.config import settings


class StoreTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, TEST_ENV)
        env.start()
        self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory()
        object.__setattr__(settings, "db_path", str(Path(self.temp.name) / "test.sqlite"))
        db.init_db()
        settings_store.seed()

    def tearDown(self):
        self.temp.cleanup()

    def test_migration_and_non_overwrite_after_env_removed(self):
        old = settings_store.active()
        self.assertEqual(old["image"], "ghcr.io/test/worker:v1")
        with patch.dict(os.environ, {key: "" for key in settings_store.ENV_KEYS.values()}):
            settings_store.seed()
            self.assertEqual(settings_store.active(), old)

    def test_draft_never_redirects_active_group(self):
        original = settings.salad_group_name
        proposed = {"image": "ghcr.io/test/worker:v2", "group_name": "test-group-v2",
                    "display_name": "Test Group V2"}
        updated = settings_store.save_draft(proposed)
        self.assertEqual(updated["draft"], proposed)
        self.assertEqual(updated["active"]["group_name"], original)
        self.assertEqual(settings.salad_group_name, original)
        self.assertTrue(updated["has_changes"])

    def test_repeated_save_preserves_provisioning_candidate(self):
        proposed = {"image": "ghcr.io/test/worker:v2", "group_name": "test-group-v2",
                    "display_name": "Test Group V2"}
        settings_store.save_draft(proposed)
        settings_store.provisioning({"draft": proposed, "group_name": "test-group-v2-a1b2c3d4"})
        again = settings_store.save_draft(proposed)
        self.assertEqual(again["provisioning"]["group_name"], "test-group-v2-a1b2c3d4")

    def test_reject_running_gpu_before_api_writes(self):
        settings_store.save_draft({"image": "ghcr.io/test/worker:v2",
                                   "group_name": "test-group-v1", "display_name": "Test Group V1"})
        running = {"replicas": 1, "pending_change": False,
                   "queue_autoscaler": {"min_replicas": 0},
                   "container": {"image": "ghcr.io/test/worker:v1"}}
        with patch.object(salad_control, "_get_group", return_value=running), \
             patch.object(salad_control, "_api") as call:
            with self.assertRaisesRegex(ValueError, "Active GPU"):
                salad_control.deploy_draft()
            call.assert_not_called()
            self.assertEqual(settings_store.active()["image"], "ghcr.io/test/worker:v1")

    def test_in_place_idle_image_upgrade(self):
        settings_store.save_draft({"image": "ghcr.io/test/worker:v2",
                                   "group_name": "test-group-v1", "display_name": "Test Group V1"})
        old = {"replicas": 0, "pending_change": False,
               "queue_autoscaler": {"min_replicas": 0},
               "container": {"image": "ghcr.io/test/worker:v1"},
               "current_state": {"status": "running"}}
        with patch.object(salad_control, "_get_group", return_value=old), \
             patch.object(salad_control, "_ensure_queue"), \
             patch.object(salad_control, "_wait_settled", return_value=old), \
             patch.object(salad_control, "_api") as api:
            result = salad_control.deploy_draft()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["active"]["image"], "ghcr.io/test/worker:v2")
        api.assert_called_once_with("PATCH", salad_control._group_path("test-group-v1"),
                                    payload={"container": {"image": "ghcr.io/test/worker:v2"}})

    def test_name_conflict_allocates_unique_group_and_preserves_old(self):
        desired = {"image": "ghcr.io/test/worker:v2", "group_name": "test-group-v2",
                   "display_name": "Test Group V2"}
        settings_store.save_draft(desired)
        old = {"replicas": 0, "pending_change": False,
               "queue_autoscaler": {"min_replicas": 0},
               "container": {"image": "ghcr.io/test/worker:v1"},
               "current_state": {"status": "running"}}
        calls = []
        def fake_get(name):
            calls.append(("get", name))
            return old if name == "test-group-v1" else None
        def fake_api(method, path, *, payload=None, allow_missing=False):
            calls.append((method, path))
            if method == "POST" and path.endswith("/containers") and len([x for x in calls if x[0]=="POST" and x[1].endswith("/containers")]) == 1:
                import httpx
                response = httpx.Response(409, json={"code": "name_conflict"},
                                          request=httpx.Request("POST", "https://example.invalid"))
                raise httpx.HTTPStatusError("conflict", request=response.request, response=response)
            return {}
        with patch.object(salad_control, "_get_group", side_effect=fake_get), \
             patch.object(salad_control, "_ensure_queue"), \
             patch.object(salad_control, "_selected_gpu_id", return_value="GPU_TEST"), \
             patch.object(salad_control, "_new_group_payload", return_value={"name": "ignored"}), \
             patch.object(salad_control, "_wait_settled", return_value=old), \
             patch.object(salad_control, "_api", side_effect=fake_api):
            result = salad_control.deploy_draft()
        self.assertTrue(result["accepted"])
        self.assertTrue(result["active"]["group_name"].startswith("test-group-v2-"))
        self.assertEqual(result["active"]["image"], desired["image"])
        self.assertIn(("POST", salad_control._group_path("test-group-v1") + "/stop"), calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
