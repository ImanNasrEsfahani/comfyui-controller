"""PDF-43..47 acceptance tests. All services are fake; no paid GPU operations."""
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from io import BytesIO

TEST_ENV = {
    "APP_NAME": "axis-test", "DB_PATH": "/tmp/axis-test-unused.db", "MAX_UPLOAD_MB": "10",
    "APP_INTERNAL_TOKEN": "axis-test-admin", "SALAD_API_KEY": "fake-salad-secret",
    "SALAD_API_BASE_URL": "https://provider.invalid", "SALAD_USER_AGENT": "axis-tests",
    "SALAD_HTTP_TIMEOUT_SECONDS": "1", "SALAD_ORG": "test-org", "SALAD_PROJECT": "test-project",
    "SALAD_QUEUE_NAME": "test-queue", "SALAD_PRIORITY": "medium", "SALAD_GPU_NAME": "test-gpu",
    "SALAD_LEGACY_QUEUE": "legacy-queue", "SALAD_IMAGE": "ghcr.io/test/worker:v1",
    "SALAD_CONTAINER_GROUP_NAME": "test-group", "SALAD_CONTAINER_GROUP_DISPLAY_NAME": "Test group",
    "R2_ENDPOINT_URL": "https://storage.invalid", "R2_BUCKET": "test-bucket",
    "R2_ACCESS_KEY_ID": "fake-access", "R2_SECRET_ACCESS_KEY": "fake-storage-secret",
    "R2_REGION": "auto", "R2_PRESIGN_TTL_SECONDS": "60", "DIRECT_QUEUE_ENABLED": "true",
    "DIRECT_GPU_AUTO_CONTROL": "false", "DIRECT_WORKER_TOKEN": "w" * 48,
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)

from app import db, direct_queue as queue, storage, contracts, salad_control, instance_contract
from app.config import settings
from app.main import app

ADMIN = {"X-Internal-Token": settings.internal_token}
WORKER = {"X-Worker-Token": "w" * 48}
WF = {"1": {"class_type": "Test", "inputs": {"text": "{{prompt.user}}", "seed": "{{generation.seed}}"}}}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    object.__setattr__(settings, "db_path", str(tmp_path / "controller.db"))
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("DIRECT_GPU_AUTO_CONTROL", "false")
    monkeypatch.setenv("DIRECT_WORKER_TOKEN", "w" * 48)
    monkeypatch.setattr(storage, "sign_s3_values", lambda value: value)
    monkeypatch.setattr(storage, "presign_get", lambda key: "https://signed.invalid/" + key)
    monkeypatch.setattr(storage, "client", lambda: (_ for _ in ()).throw(AssertionError("R2 must be mocked")))
    monkeypatch.setattr(salad_control, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Salad must be mocked")))
    db.init_db()
    queue.save_setting("salad_active", {"image": "ghcr.io/test/worker:v1", "group_name": "test-group", "display_name": "Test"})
    db.save_workflow("wf", "Test", WF)


def request(prompt="A", key="request-A"):
    return {"contract_version": 1, "client_request_id": key, "workflow_id": "wf",
            "workflow_version": contracts.digest(WF), "variables": {"prompt.user": prompt, "generation.seed": 17}}


def submit(body=None):
    with TestClient(app) as client:
        response = client.post("/api/jobs", json=body or request(), headers=ADMIN)
        assert response.status_code == 200, response.text
        return response.json()


def fake_store(monkeypatch, unavailable=()):
    class Store:
        def head_object(self, *, Key, **kwargs):
            if Key.rsplit("/", 1)[-1] in unavailable:
                raise FileNotFoundError(Key)
            return {"ContentLength": 100, "ContentType": "image/png", "Metadata": {"width": "512", "height": "768"}}
        def get_paginator(self, name):
            class Pages:
                def paginate(self, **kwargs): return [{"Contents": []}]
            return Pages()
    monkeypatch.setattr(storage, "client", lambda: Store())


def _png_bytes():
    content = BytesIO()
    Image.new("RGB", (12, 8), (40, 90, 140)).save(content, format="PNG")
    return content.getvalue()


def test_upload_checks_actual_image_bytes_type_size_and_persists_metadata(monkeypatch):
    transferred = []
    monkeypatch.setattr(storage, "upload_fileobj", lambda stream, key, content_type: transferred.append((stream.read(), key, content_type)))
    png = _png_bytes()
    with TestClient(app) as client:
        valid = client.post("/api/uploads", headers=ADMIN, files={"file": ("sample.png", png, "image/png")})
        corrupt = client.post("/api/uploads", headers=ADMIN, files={"file": ("fake.png", b"not an image", "image/png")})
        mismatch = client.post("/api/uploads", headers=ADMIN, files={"file": ("renamed.jpg", png, "image/jpeg")})
    assert valid.status_code == 200, valid.text
    data = valid.json()
    assert data["mime_type"] == "image/png" and data["width"] == 12 and data["height"] == 8
    assert data["size_bytes"] == len(png) and data["s3_uri"].endswith("/sample.png")
    assert len(transferred) == 1 and transferred[0][0] == png and transferred[0][2] == "image/png"
    with db.connect() as conn:
        asset = conn.execute("SELECT * FROM input_assets WHERE asset_id=?", (data["asset_id"],)).fetchone()
    assert asset and asset["mime_type"] == "image/png" and asset["width"] == 12 and asset["size_bytes"] == len(png)
    assert corrupt.status_code == 422 and mismatch.status_code == 422


def test_upload_rejects_files_over_configured_limit(monkeypatch):
    oversized = b"x" * (settings.max_upload_mb * 1024 * 1024 + 1)
    with TestClient(app) as client:
        response = client.post("/api/uploads", headers=ADMIN, files={"file": ("large.png", oversized, "image/png")})
    assert response.status_code == 413


def test_verified_output_can_be_reused_as_reference_and_download_is_job_scoped(monkeypatch):
    source = submit()
    other_job = submit(request("A different private Job", "another-job"))
    key = f"outputs/{source['id']}/attempt-a/generated.png"
    asset = {"asset_id": "verified-output-1", "job_id": source["id"], "attempt_id": "attempt-a",
        "storage_key": key, "media_type": "image", "mime_type": "image/png", "width": 12, "height": 8,
        "size_bytes": 96, "duration_seconds": None, "frame_rate": None, "status": "available",
        "verified_at": db.utcnow(), "error_code": None, "created_at": db.utcnow()}
    with db.connect() as conn:
        from app.job_records import save_assets
        save_assets(conn, [asset])
    workflow = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_1}}"}},
                "2": {"class_type": "Test", "inputs": {"text": "{{prompt.user}}"}}}
    db.save_workflow("image-wf", "Image workflow", workflow)
    uri = f"s3://{settings.r2_bucket}/{key}"
    request_body = {"contract_version": 1, "client_request_id": "reuse-output", "workflow_id": "image-wf",
        "workflow_version": contracts.digest(workflow), "priority": "medium",
        "variables": {"prompt.user": "reuse", "input.image_1": uri}}
    monkeypatch.setattr(storage, "presign_get", lambda storage_key, *args, **kwargs: "https://signed.invalid/download")
    class StreamBody:
        closed = False
        def iter_chunks(self, chunk_size):
            assert chunk_size == 1024 * 1024
            yield b"image-bytes-"
            yield b"here"
        def close(self):
            self.closed = True
    body = StreamBody()
    monkeypatch.setattr(storage, "get_object", lambda storage_key: {
        "Body": body, "ContentLength": 16, "ContentType": "image/png"})
    with TestClient(app) as client:
        accepted = client.post("/api/jobs", json=request_body, headers=ADMIN)
        downloaded = client.get(f"/api/jobs/{source['id']}/assets/verified-output-1/download", headers=ADMIN, follow_redirects=False)
        wrong_job = client.get(f"/api/jobs/{other_job['id']}/assets/verified-output-1/download", headers=ADMIN, follow_redirects=False)
        unauthenticated = client.get(f"/api/jobs/{source['id']}/assets/verified-output-1/download")
    assert accepted.status_code == 200, accepted.text
    reference = accepted.json()["snapshot"]["references"][0]
    assert reference["uri"] == uri and reference["asset_id"] == "verified-output-1" and reference["source_job_id"] == source["id"]
    assert downloaded.status_code == 200
    assert downloaded.content == b"image-bytes-here"
    assert downloaded.headers["content-disposition"].endswith("filename*=UTF-8''generated.png")
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert body.closed
    assert wrong_job.status_code == 404
    assert unauthenticated.status_code == 401


def complete(job, claim, filenames=("image.png",)):
    output = {"images": [f"s3://{settings.r2_bucket}/{claim['request']['s3']['prefix']}{name}" for name in filenames]}
    assert queue.finish(job["id"], claim["lease_token"], output, claim["attempt_id"])
    return output


def test_latest_prompt_snapshot_worker_and_regenerate():
    a = submit()
    b_body = request("B", "request-B")
    b_body["source_job_id"] = a["id"]
    b = submit(b_body)
    assert a["snapshot"]["positive_prompt"] == "A"
    assert db.get_job(a["id"])["snapshot"] == a["snapshot"]
    assert b["snapshot"]["positive_prompt"] == "B"
    assert b["snapshot"]["seed"] == 17
    claim_a = queue.claim("worker")
    assert claim_a["request"]["prompt"]["1"]["inputs"]["text"] == "A"
    queue.fail(a["id"], claim_a["lease_token"], "test failure", False)
    claim_b = queue.claim("worker")
    assert claim_b["request"]["prompt"]["1"]["inputs"]["text"] == "B"
    assert b["source_job_id"] == a["id"] and b["id"] != a["id"]


def test_atomic_acceptance_duplicate_conflict_recovery_and_workflow_change():
    body = request()
    with ThreadPoolExecutor(max_workers=6) as pool:
        accepted = list(pool.map(lambda _: submit(body), range(6)))
    assert len({job["id"] for job in accepted}) == 1
    assert len(db.list_jobs()) == 1
    db.save_workflow("wf", "Changed", {"2": {"inputs": {"text": "fixed"}}})
    assert submit(body)["id"] == accepted[0]["id"]
    with TestClient(app) as client:
        recovered = client.get("/api/job-requests/request-A", headers=ADMIN)
        assert recovered.json()["id"] == accepted[0]["id"]
        changed = client.post("/api/jobs", json=request("B"), headers=ADMIN)
        assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
        changed = client.post("/api/jobs", json=request("B", "new-key"), headers=ADMIN)
        assert changed.status_code == 409 and changed.json()["error"]["code"] == "workflow_changed"
        assert client.get("/api/job-requests/request-A").status_code == 401


@pytest.mark.parametrize("change,code", [
    ({"contract_version": 2}, "unsupported_contract_version"),
    ({"variables": {"prompt.user": "A", "generation.seed": "17"}}, "invalid_integer"),
    ({"variables": {"prompt.user": "A", "generation.seed": 17, "prompt.hidden": "ignored"}}, "unsupported_variable"),
    ({"variables": {"prompt.user": "A", "generation.seed": 17, "app.token": "secret"}}, "sensitive_field"),
    ({"variables": {"prompt.user": settings.internal_token, "generation.seed": 17}}, "sensitive_value"),
    ({"variables": {"prompt.user": "A"}}, "missing_variable"),
    ({"model_id": "unsupported-selector"}, "extra_forbidden"),
    ({"variables": {"prompt.user": "A", "generation.seed": 9007199254740992}}, "invalid_range"),
])
def test_validation_errors_are_stable_and_do_not_echo_credentials(change, code):
    with TestClient(app) as client:
        response = client.post("/api/jobs", headers=ADMIN, json={**request(), **change})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert "path" in response.json()["error"]
    assert settings.internal_token not in response.text
    assert not db.list_jobs()


def test_non_finite_numbers_are_rejected_by_the_backend_contract():
    with pytest.raises(contracts.ContractError) as error:
        contracts.validate_variables(WF, {"prompt.user": "A", "generation.seed": 17, "generation.cfg": float("nan")})
    assert error.value.code == "invalid_number"
    assert error.value.path == "variables.generation.cfg"


def test_reference_images_must_be_controller_uploaded_input_assets():
    image_wf = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_1}}"}},
                "2": {"class_type": "Test", "inputs": {"text": "{{prompt.user}}"}}}
    db.save_workflow("image-wf", "Image workflow", image_wf)
    body = {"contract_version": 1, "client_request_id": "valid-image", "workflow_id": "image-wf",
            "workflow_version": contracts.digest(image_wf), "priority": "medium",
            "variables": {"prompt.user": "portrait", "input.image_1": "s3://test-bucket/inputs/asset-1/photo.png"}}
    with TestClient(app) as client:
        accepted = client.post("/api/jobs", headers=ADMIN, json=body)
        assert accepted.status_code == 200, accepted.text
        invalid = {**body, "client_request_id": "invalid-image", "variables": {
            **body["variables"], "input.image_1": "https://attacker.invalid/photo.png"}}
        rejected = client.post("/api/jobs", headers=ADMIN, json=invalid)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "invalid_reference"
    assert rejected.json()["error"]["path"] == "variables.input.image_1"
    assert len(db.list_jobs()) == 1


def test_legacy_input_contract_still_works():
    body = request()
    del body["contract_version"]; del body["workflow_version"]; del body["client_request_id"]
    accepted = submit(body)
    assert accepted["job_id"] == accepted["id"]
    assert accepted["status"] == "queued" and accepted["state"] == "pending"


def test_snapshot_cannot_be_mutated_in_sql():
    job = submit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.connect() as c:
            c.execute("UPDATE jobs SET snapshot_json='{}' WHERE id=?", (job["id"],))
    assert db.get_job(job["id"])["snapshot"] == job["snapshot"]


def test_finalizing_file_validation_partial_success_and_duplicate_callback(monkeypatch):
    fake_store(monkeypatch, unavailable=("missing.png",))
    job = submit()
    claim = queue.claim("worker")
    original = storage.validate_outputs
    def validate(*args):
        assert db.get_job(job["id"])["state"] == "finalizing"
        assert queue.counters()["running"] == 1
        assert queue.claim("second-worker") is None
        return original(*args)
    monkeypatch.setattr(storage, "validate_outputs", validate)
    output = complete(job, claim, ("image.png", "missing.png"))
    first = db.get_job(job["id"])
    assert first["state"] == "succeeded" and first["finished_at"]
    assert len(first["assets"]) == 2 and first["assets"][0]["attempt_id"] == claim["attempt_id"]
    assert queue.finish(job["id"], claim["lease_token"], output, claim["attempt_id"])
    assert db.get_job(job["id"])["version"] == first["version"]
    assert not queue.finish(job["id"], claim["lease_token"], {"overwrite": True})
    with TestClient(app) as client:
        data = client.get(f"/api/jobs/{job['id']}", headers=ADMIN).json()
        assert data["output_summary"]["partial_success"]
        assert "lease_token_hash" not in json.dumps(data)
        images = client.get(f"/api/jobs/{job['id']}/images", headers=ADMIN).json()
        assert len(images["images"]) == 1 and len(images["assets"]) == 2
        assert images["images"][0]["width"] == 512
    assert [event["state"] for event in first["timeline"]] == ["pending", "running", "finalizing", "succeeded"]


def test_no_output_is_not_success_and_retry_keeps_attempt_history(monkeypatch):
    fake_store(monkeypatch)
    job = submit()
    first = queue.claim("worker-1")
    assert queue.finish(job["id"], first["lease_token"], {"images": []}, first["attempt_id"])
    assert db.get_job(job["id"])["state"] == "failed"
    with TestClient(app) as client:
        retried = client.post(f"/api/jobs/{job['id']}/retry", headers=ADMIN, json={})
        assert retried.json()["id"] == job["id"]
    second = queue.claim("worker-2")
    assert second["attempt_id"] != first["attempt_id"]
    assert second["request"]["s3"]["prefix"] != first["request"]["s3"]["prefix"]
    assert not queue.heartbeat(job["id"], first["lease_token"], first["attempt_id"])
    assert not queue.finish(job["id"], first["lease_token"], {"old": True})
    complete(job, second)
    history = db.get_job(job["id"])["attempt_history"]
    assert [a["state"] for a in history] == ["failed", "succeeded"]
    assert history[1]["previous_attempt_id"] == history[0]["id"]


def test_r2_outage_keeps_finalizing_and_can_recover(monkeypatch):
    job = submit(); claim = queue.claim("worker")
    with TestClient(app) as client:
        failed = client.post(f"/api/worker/complete/{job['id']}", headers=WORKER,
            json={"lease_token": claim["lease_token"], "attempt_id": claim["attempt_id"], "output": {}})
    assert failed.status_code == 502
    assert db.get_job(job["id"])["state"] == "finalizing"
    assert queue.heartbeat(job["id"], claim["lease_token"], claim["attempt_id"])
    fake_store(monkeypatch)
    complete(job, claim)


def test_illegal_transition_terminal_race_and_version_fence(monkeypatch):
    fake_store(monkeypatch)
    job = submit(); claim = queue.claim("worker")
    old_version = job["version"]
    assert not db.update_job(job["id"], state="failed", expected_version=old_version)
    complete(job, claim)
    with pytest.raises(ValueError, match="Invalid Job transition"):
        db.update_job(job["id"], state="running")
    with pytest.raises(sqlite3.IntegrityError, match="invalid Job transition"):
        with db.connect() as c: c.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
    assert not queue.cancel_pending(job["id"])
    assert db.get_job(job["id"])["state"] == "succeeded"


def test_expired_attempt_has_history_and_no_old_lease_can_commit(monkeypatch):
    job = submit(); first = queue.claim("worker-1")
    now = queue._time()
    monkeypatch.setattr(queue, "_time", lambda: now + 200)
    assert queue.recover_expired() == 1
    assert db.get_job(job["id"])["state"] == "pending"
    monkeypatch.setattr(queue, "_time", lambda: now + 400)
    second = queue.claim("worker-2")
    assert second["attempt_id"] != first["attempt_id"]
    assert not queue.heartbeat(job["id"], second["lease_token"], first["attempt_id"])
    assert db.get_job(job["id"])["attempt_history"][0]["state"] == "expired"


def test_infrastructure_financial_unknowns_sessions_secrets_and_freshness(monkeypatch):
    group = {"name": "test-group", "replicas": 1, "current_state": {"status": "running"},
             "container": {"environment_variables": {"SECRET": "NEVER_RETURN"}}}
    observed = [{"id": "instance-1", "state": "running", "ready": True, "pulling_progress": .7,
                 "untrusted": "NEVER_RETURN"}]
    monkeypatch.setattr(salad_control, "request", lambda method, suffix="", **kwargs: {"instances": observed} if suffix else group)
    queue.worker_seen("worker")
    first = salad_control.status()
    assert first["worker_status"] == "connected"
    assert first["readiness"] == "unknown"
    assert first["worker"]["runtime_readiness"] == "unknown"
    assert "runtime readiness is not verified" in first["readiness_reason"]
    assert "ready" not in first["instances"][0]
    assert first["instances"][0]["provider_ready"] is True
    assert first["instances"][0]["pull_progress"]["unit"] is None
    assert first["financial"]["balance"] is None and first["financial"]["estimated_cost"] is None
    assert "NEVER_RETURN" not in json.dumps(first)
    assert first["sessions"][0]["first_ready_at"] is None
    observed.clear(); group["replicas"] = 0
    newer = salad_control.status()
    assert newer["worker_status"] == "disconnected" and newer["sessions"][0]["stopped_at"]
    assert newer["readiness"] == "not_ready"
    assert instance_contract.record(first, first["version"], first["last_updated_at"]) == newer
    assert newer["version"] > first["version"]


def test_legacy_migration_retains_exact_payloads_and_unknown_historic_times(tmp_path):
    old = tmp_path / "legacy.db"
    with sqlite3.connect(old) as c:
        c.executescript("CREATE TABLE jobs(id TEXT PRIMARY KEY,salad_job_id TEXT,workflow_id TEXT,state TEXT NOT NULL,request_json TEXT NOT NULL,output_json TEXT,error_text TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);")
        c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)", ("old", "remote", "wf", "succeeded", '{"original":1}', '{"legacy":true}', None, "2026-01-01", "2026-01-02"))
    object.__setattr__(settings, "db_path", str(old))
    db.init_db(); db.init_db()
    row = db.get_job("old")
    assert row["request"] == {"original": 1} and row["output"] == {"legacy": True}
    assert row["snapshot"] is None and row["started_at"] is None and row["finished_at"] is None
    assert row["attempt_history"] == [] and row["salad_job_id"] == "remote"


def test_failed_database_migration_rolls_back_schema_and_state_guards(monkeypatch):
    job = submit()
    real_migrate = db.job_records.migrate

    def fail_migration(conn):
        real_migrate(conn)
        conn.execute("ALTER TABLE jobs ADD COLUMN rollback_probe TEXT")
        conn.execute("DROP TRIGGER jobs_transition_guard")
        raise RuntimeError("controlled migration failure")

    monkeypatch.setattr(db.job_records, "migrate", fail_migration)
    with pytest.raises(RuntimeError, match="controlled migration failure"):
        db.init_db()
    with db.connect() as conn:
        assert "rollback_probe" not in {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='jobs_transition_guard'").fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="invalid Job transition"):
            conn.execute("UPDATE jobs SET state='submit_failed' WHERE id=?", (job["id"],))


def test_fixed_workflow_capabilities_are_descriptive_not_invented():
    wf = {"id": "wf", "api_prompt": {"1": {"class_type": "LoraLoader", "inputs": {"lora_name": "actual.safetensors", "strength_model": .8}}}}
    snap = contracts.effective_snapshot(wf, {}, "medium")
    assert snap["loras"][0]["version"] is None
    assert snap["validated_model_capabilities"] is None
    assert snap["output_spec"]["width"] is None


def test_new_salad_queue_attempt_snapshot_and_verified_completion(monkeypatch):
    from app import main
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "false")
    monkeypatch.setattr(main.salad, "submit_job", lambda *args, **kwargs: ({"id": "remote-job", "status": "pending"}, "test-queue", "medium"))
    fake_store(monkeypatch)
    accepted = submit()
    assert accepted["attempt_history"][0]["started_at"] is None
    assert accepted["active_attempt_id"]
    monkeypatch.setattr(main.salad, "get_job", lambda *args: {"status": "succeeded", "output": {"image": f"s3://{settings.r2_bucket}/outputs/{accepted['id']}/result.png"}})
    with TestClient(app) as client:
        completed = client.get(f"/api/jobs/{accepted['id']}", headers=ADMIN)
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["state"] == "succeeded" and result["assets"][0]["attempt_id"] == result["active_attempt_id"]
    assert result["attempt_history"][0]["state"] == "succeeded"
    assert [e["state"] for e in result["timeline"]] == ["submitting", "pending", "finalizing", "succeeded"]


def test_verified_success_cannot_be_set_without_assets():
    job = submit(); claim = queue.claim("worker")
    with pytest.raises(sqlite3.IntegrityError, match="requires verified"):
        with db.connect() as c: c.execute("UPDATE jobs SET state='succeeded' WHERE id=?", (job["id"],))
    assert db.get_job(job["id"])["state"] == "running"


def test_new_legacy_provider_retries_are_linked_without_changing_original_snapshot(monkeypatch):
    from app import main
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "false")
    monkeypatch.setattr(main.salad, "submit_job", lambda *args, **kwargs: ({"id": "remote-job", "status": "failed"}, "test-queue", "medium"))
    job = submit()
    with TestClient(app) as client:
        retried = client.post(f"/api/jobs/{job['id']}/retry", headers=ADMIN, json={})
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == job["id"]
    assert len(retried.json()["attempt_history"]) == 2
    assert retried.json()["attempt_history"][1]["previous_attempt_id"] == job["active_attempt_id"]
    assert db.get_job(job["id"])["snapshot"] == job["snapshot"]


def test_worker_keeps_heartbeat_during_result_acknowledgement(monkeypatch):
    import importlib.util
    import threading
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("axis_worker_test", Path(__file__).resolve().parents[1] / "salad-worker/pull_worker.py")
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", .01)
    monkeypatch.setattr(worker, "execute", lambda job: {"image": "stored output"})
    heartbeat_seen = threading.Event()
    sent = []
    def acknowledge(path, data):
        sent.append((path, data))
        if "/heartbeat/" in path:
            heartbeat_seen.set(); return {"accepted": True}
        assert heartbeat_seen.wait(1), "Heartbeat stopped before finalization acknowledgement"
        return {"accepted": True, "state": "succeeded"}
    monkeypatch.setattr(worker, "request", acknowledge)
    worker.work({"job_id": "test-job", "attempt": 1, "attempt_id": "attempt-1", "lease_token": "t" * 64})
    assert all(data["attempt_id"] == "attempt-1" for _, data in sent)


def test_r2_server_error_is_a_recoverable_finalizing_outage(monkeypatch):
    from botocore.exceptions import ClientError
    class Store:
        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}}, "HeadObject")
    monkeypatch.setattr(storage, "client", lambda: Store())
    job = submit(); claim = queue.claim("worker")
    with pytest.raises(ClientError):
        queue.finish(job["id"], claim["lease_token"], {"image": f"s3://{settings.r2_bucket}/{claim['request']['s3']['prefix']}result.png"})
    assert db.get_job(job["id"])["state"] == "finalizing"


def test_new_provider_retry_wait_clock_belongs_to_latest_attempt(monkeypatch):
    from app import main
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "false")
    monkeypatch.setattr(main.salad, "submit_job", lambda *args, **kwargs: ({"id": "remote-job", "status": "failed"}, "test-queue", "medium"))
    job = submit()
    with db.connect() as c:
        c.execute("UPDATE jobs SET created_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(), job["id"]))
    monkeypatch.setattr(main.salad, "submit_job", lambda *args, **kwargs: ({"id": "remote-retry", "status": "pending"}, "test-queue", "medium"))
    with TestClient(app) as client:
        retried = client.post(f"/api/jobs/{job['id']}/retry", headers=ADMIN, json={})
        assert retried.status_code == 200
        assert client.get("/api/jobs", headers=ADMIN).json()[0]["state"] == "pending"


def test_private_job_media_upload_workflow_and_infrastructure_routes_require_admin_access():
    with TestClient(app) as client:
        private_reads = [
            ("/api/jobs", {}),
            ("/api/jobs/history", {}),
            ("/api/jobs/private-job", {}),
            ("/api/jobs/private-job/draft", {}),
            ("/api/jobs/private-job/images", {}),
            ("/api/jobs/private-job/assets/private-asset/download", {}),
            ("/api/job-comparison?first_id=one&second_id=two", {}),
            ("/api/job-requests/private-request", {}),
            ("/api/workflows/wf", {}),
            ("/api/salad/instances", {}),
        ]
        for path, _ in private_reads:
            assert client.get(path).status_code == 401, path

        assert client.post("/api/jobs", json=request()).status_code == 401
        assert client.post("/api/uploads", files={"file": ("input.png", _png_bytes(), "image/png")}).status_code == 401
        assert client.get("/api/jobs", headers=ADMIN).status_code == 200


def test_private_routes_fail_closed_when_admin_token_is_not_configured(monkeypatch):
    original_token = settings.internal_token
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "false")
    object.__setattr__(settings, "internal_token", "")
    try:
        with TestClient(app) as client:
            response = client.get("/api/jobs")
        assert response.status_code == 503
        assert "APP_INTERNAL_TOKEN" in response.json()["error"]["message"]
    finally:
        object.__setattr__(settings, "internal_token", original_token)
