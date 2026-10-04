"""Offline functional tests. No request is made to Salad, GHCR, or R2."""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update({
    "APP_NAME": "test-controller", "DB_PATH": "/tmp/unset-controller-db.sqlite3",
    "MAX_UPLOAD_MB": "10", "APP_INTERNAL_TOKEN": "A_FAKE_TEST_ADMIN_TOKEN",
    "SALAD_API_KEY": "TEST_SALAD_KEY", "SALAD_API_BASE_URL": "https://salad.invalid/api/public",
    "SALAD_USER_AGENT": "offline-tests/1", "SALAD_HTTP_TIMEOUT_SECONDS": "4",
    "SALAD_ORG": "test-org", "SALAD_PROJECT": "test-project",
    "SALAD_QUEUE_NAME": "test-queue", "SALAD_CONTAINER_GROUP_NAME": "test-group",
    "SALAD_PRIORITY": "medium", "SALAD_GPU_NAME": "test-gpu",
    "SALAD_LEGACY_QUEUE": "test-old-queue",
    "R2_ENDPOINT_URL": "https://r2.invalid", "R2_BUCKET": "test-bucket",
    "R2_ACCESS_KEY_ID": "TEST_ID", "R2_SECRET_ACCESS_KEY": "TEST_SECRET",
    "R2_REGION": "auto", "R2_PRESIGN_TTL_SECONDS": "3600",
    "JOB_STALE_MINUTES": "180",
    "SALAD_IMAGE": "ghcr.io/test/worker:v1", "SALAD_CONTAINER_GROUP_NAME": "test-group",
    "SALAD_CONTAINER_GROUP_DISPLAY_NAME": "Test Group",
})
from fastapi.testclient import TestClient
from app import db, salad_control, job_lifecycle, storage, settings_store
from app.main import app
from app.config import settings

ADMIN = {"X-Internal-Token": "A_FAKE_TEST_ADMIN_TOKEN"}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        object.__setattr__(settings, "db_path", str(Path(self.tmp.name) / "db.sqlite3"))
        db.init_db()
        settings_store.seed()
        db.save_workflow("test-wf", "Test workflow", {
            "1": {"inputs": {"image": "{{input.image_1}}", "text": "Prefix: {{prompt.user}}"}}
        })
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def create_local(self, *, state="pending", variables=None):
        local_id = "7fadc992-10bd-4421-98b5-03d3171c719f"
        db.create_job(local_id, "test-wf", {"prompt": {"1": {"inputs": {
            "image": "https://r2.invalid/test-bucket/inputs/old/file.jpg?X-Amz-Signature=OLD",
            "text": "Prefix: original"}}}},
            salad_queue="test-queue", variables=variables)
        db.update_job(local_id, salad_job_id="remote-1", state=state)
        return local_id

    def test_output_keys_are_scoped_and_presigned(self):
        local_id = self.create_local(state="succeeded", variables={"prompt.user": "test"})
        keys = storage.extract_output_keys({"images": [
            f"s3://test-bucket/outputs/{local_id}/result.png",
            "s3://test-bucket/inputs/secret.png",
            "s3://other-bucket/outputs/7fadc992-10bd-4421-98b5-03d3171c719f/other.png",
        ]}, local_id)
        self.assertEqual(keys, [f"outputs/{local_id}/result.png"])
        with patch.object(storage, "job_images", return_value=[{"key": keys[0], "url": "https://r2.invalid/signed"}]):
            result = self.client.get(f"/api/jobs/{local_id}/images")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()["images"]), 1)

    def test_images_use_fresh_signed_links_and_r2_fallback(self):
        local_id = "7fadc992-10bd-4421-98b5-03d3171c719f"
        known = f"s3://test-bucket/outputs/{local_id}/generated.webp"
        with patch.object(storage, "client", side_effect=PermissionError("ListBucket denied")), \
             patch.object(storage, "presign_get", return_value="https://r2.invalid/fresh-signature"):
            result = storage.job_images(local_id, {"image": known}, include_storage=True)
        self.assertEqual(result[0]["url"], "https://r2.invalid/fresh-signature")

        class Paginator:
            def paginate(self, **kwargs):
                return [{"Contents": [
                    {"Key": f"outputs/{local_id}/result.jpg"},
                    {"Key": f"inputs/{local_id}/not-output.jpg"},
                ]}]
        class Client:
            def get_paginator(self, name):
                self_name = name
                return Paginator()
        with patch.object(storage, "client", return_value=Client()), \
             patch.object(storage, "presign_get", return_value="https://r2.invalid/new-signature"):
            result = storage.job_images(local_id, {}, include_storage=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["key"], f"outputs/{local_id}/result.jpg")

    def test_submit_stores_stable_inputs_and_signs_them_on_each_attempt(self):
        from app import main
        input_ref = "s3://test-bucket/inputs/123/photo.png"
        vars_ = {"input.image_1": input_ref, "prompt.user": "Improve lighting"}
        with patch.object(storage, "sign_s3_values", side_effect=lambda value:
                          {k: "https://r2.invalid/new-signed-url" if k == "input.image_1" else v
                           for k, v in value.items()} if isinstance(value, dict) else value), \
             patch.object(main.salad, "submit_job", return_value=({"id": "new-remote", "status": "pending"}, "test-queue", "medium")):
            result = self.client.post("/api/jobs", headers=ADMIN,
                                      json={"workflow_id": "test-wf", "variables": vars_})
        self.assertEqual(result.status_code, 200, result.text)
        job = db.get_job(result.json()["id"])
        self.assertEqual(job["variables"], vars_)
        self.assertEqual(job["request"]["prompt"]["1"]["inputs"]["image"],
                         "https://r2.invalid/new-signed-url")
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}/draft").json()["variables"], vars_)

    def test_stalled_is_not_falsely_reported_as_failure_and_can_recover(self):
        from app import main
        local_id = self.create_local()
        old = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET created_at=? WHERE id=?", (old, local_id))
        result = self.client.get("/api/jobs").json()[0]
        self.assertEqual(result["state"], "stalled")
        self.assertIn("not a confirmed failure", result["error_text"])
        with patch.object(main.salad, "get_job", return_value={"status": "succeeded", "output": {"done": True}}):
            result = self.client.get(f"/api/jobs/{local_id}")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["state"], "succeeded")

    def test_hide_does_not_cancel_remote_job(self):
        local_id = self.create_local()
        self.assertEqual(self.client.delete(f"/api/jobs/{local_id}").status_code, 401)
        with patch("app.main.salad.get_job") as remote:
            self.assertEqual(self.client.delete(f"/api/jobs/{local_id}", headers=ADMIN).status_code, 204)
            remote.assert_not_called()
        self.assertEqual(self.client.get("/api/jobs").json(), [])
        self.assertEqual(db.get_job(local_id)["salad_job_id"], "remote-1")

    def test_retry_stalled_requires_explicit_duplicate_confirmation(self):
        from app import main
        vars_ = {"input.image_1": "s3://test-bucket/inputs/u/photo.png", "prompt.user": "new"}
        local_id = self.create_local(state="stalled", variables=vars_)
        self.assertEqual(self.client.post(f"/api/jobs/{local_id}/retry", headers=ADMIN,
                                           json={}).status_code, 409)
        with patch.object(storage, "sign_s3_values", side_effect=lambda v: v), \
             patch.object(main.salad, "submit_job", return_value=({"id": "retry-remote", "status": "pending"}, "test-queue", "medium")):
            result = self.client.post(f"/api/jobs/{local_id}/retry", headers=ADMIN,
                                      json={"allow_duplicate": True})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotEqual(result.json()["id"], local_id)
        self.assertEqual(result.json()["variables"], vars_)

    def test_legacy_draft_recovery(self):
        vars_ = job_lifecycle.legacy_draft(
            {"image": "{{input.image_1}}", "text": "Prefix: {{prompt.user}}"},
            {"image": "https://r2.invalid/test-bucket/inputs/u/photo.png?X-Amz-Signature=abc",
             "text": "Prefix: editable old prompt"},
        )
        self.assertEqual(vars_["input.image_1"], "s3://test-bucket/inputs/u/photo.png")
        self.assertEqual(vars_["prompt.user"], "editable old prompt")
        self.assertEqual(job_lifecycle.recover_image_ref("https://untrusted.invalid/a.png"), "")

    def test_instances_are_sanitized_and_stop_requires_authentication(self):
        group = {"name": "test-group", "replicas": 1,
                 "pending_change": False,
                 "current_state": {"status": "running", "instance_status_counts": {"running_count": 1}},
                 "queue_autoscaler": {"max_replicas": 1},
                 "container": {"environment_variables": {"AWS_SECRET_ACCESS_KEY": "DO_NOT_LEAK"}}}
        def fake_request(method, suffix="", **kwargs):
            if method == "GET" and suffix == "/instances":
                return {"instances": [{"id": "instance1", "state": "running", "ready": True,
                                        "secret_field": "DO_NOT_LEAK"}]}
            if method == "GET": return group
            return {}
        with patch.object(salad_control, "request", side_effect=fake_request) as request:
            data = self.client.get("/api/salad/instances")
            self.assertEqual(data.status_code, 200)
            self.assertNotIn("DO_NOT_LEAK", data.text)
            self.assertEqual(data.json()["instances"][0]["state"], "running")
            self.assertEqual(self.client.post("/api/salad/stop").status_code, 401)
            self.assertEqual(self.client.post("/api/salad/stop", headers=ADMIN).status_code, 200)
            self.assertTrue(any(c.args[:2] == ("POST", "/stop") for c in request.call_args_list))

    def test_stop_denied_during_pending_change(self):
        with patch.object(salad_control, "request", return_value={"pending_change": True}):
            self.assertEqual(self.client.post("/api/salad/stop", headers=ADMIN).status_code, 409)

    def test_db_schema_migration_idempotent(self):
        db.init_db()
        db.init_db()
        with db.connect() as c:
            columns = {row["name"] for row in c.execute("PRAGMA table_info(jobs)")}
        self.assertTrue({"variables_json", "hidden", "salad_queue", "priority"} <= columns)

if __name__ == "__main__":
    unittest.main()
