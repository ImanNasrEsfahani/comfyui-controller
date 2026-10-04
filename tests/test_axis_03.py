"""Axis 3 capability contract and worker pass-through tests; no GPU is started."""
import importlib.util
import os
from pathlib import Path

import pytest

TEST_ENV = {
    "APP_NAME": "axis-test", "DB_PATH": "/tmp/axis3-unused.db", "MAX_UPLOAD_MB": "10",
    "APP_INTERNAL_TOKEN": "axis-test-admin", "SALAD_API_KEY": "fake-salad-secret",
    "SALAD_API_BASE_URL": "https://provider.invalid", "SALAD_USER_AGENT": "axis3-tests",
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

from app import contracts, db, direct_queue as queue, main as controller, salad_control, storage
from app.config import settings
WORKFLOW = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_1}}"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt.positive}}", "clip": ["5", 1]}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt.negative}}", "clip": ["5", 1]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "qwen-edit.safetensors"}},
    "5": {"class_type": "LoraLoader", "inputs": {
        "lora_name": "{{lora.style.name}}", "strength_model": "{{lora.style.strength_model}}",
        "strength_clip": "{{lora.style.strength_clip}}", "model": ["4", 0], "clip": ["4", 1]}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": "{{generation.seed}}", "steps": "{{generation.steps}}", "cfg": "{{generation.cfg}}",
        "sampler_name": "{{generation.sampler}}", "scheduler": "{{generation.scheduler}}",
        "model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0]}},
    "7": {"class_type": "EmptyLatentImage", "inputs": {
        "width": "{{output.width}}", "height": "{{output.height}}", "batch_size": 1}},
    "8": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
}
CAPABILITY_SPEC = {
    "schema_version": 1,
    "operation": "image_edit",
    "model": {"id": "qwen-edit", "label": "Qwen Image Edit", "version": "workflow-1"},
    "fields": {
        "generation.seed": {"kind": "integer", "label": "Seed", "minimum": 0, "maximum": 1000000, "default": 42, "advanced": True},
        "generation.steps": {"kind": "integer", "label": "Steps", "minimum": 1, "maximum": 50, "default": 8, "advanced": True},
        "generation.cfg": {"kind": "number", "label": "CFG", "minimum": 0, "maximum": 20, "default": 4, "step": 0.1, "advanced": True},
        "generation.sampler": {"kind": "select", "label": "Sampler", "options": ["euler", "dpmpp_2m"], "default": "euler", "advanced": True},
        "generation.scheduler": {"kind": "select", "label": "Scheduler", "options": ["normal", "karras"], "default": "normal", "advanced": True},
        "lora.style.name": {"kind": "select", "label": "Style LoRA", "options": ["soft-style.safetensors", "line-style.safetensors"], "default": "soft-style.safetensors", "advanced": True},
        "lora.style.strength_model": {"kind": "number", "label": "LoRA model strength", "minimum": 0, "maximum": 2, "step": 0.01, "default": 0.8, "advanced": True},
        "lora.style.strength_clip": {"kind": "number", "label": "LoRA CLIP strength", "minimum": 0, "maximum": 2, "step": 0.01, "default": 0.6, "advanced": True},
        "output.width": {"kind": "integer", "label": "Width", "minimum": 64, "maximum": 2048, "step": 64, "default": 512, "advanced": True},
        "output.height": {"kind": "integer", "label": "Height", "minimum": 64, "maximum": 2048, "step": 64, "default": 512, "advanced": True},
    },
    "reference_inputs": [{"variable_key": "input.image_1", "label": "Identity reference", "role": "identity", "order": 0, "required": True}],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    object.__setattr__(settings, "db_path", str(tmp_path / "controller.db"))
    monkeypatch.setenv("DIRECT_QUEUE_ENABLED", "true")
    monkeypatch.setenv("DIRECT_GPU_AUTO_CONTROL", "false")
    monkeypatch.setenv("DIRECT_WORKER_TOKEN", "w" * 48)
    monkeypatch.setattr(storage, "sign_s3_values", lambda value: value)
    monkeypatch.setattr(storage, "presign_get", lambda key: "https://signed.invalid/" + key)
    monkeypatch.setattr(storage, "client", lambda: (_ for _ in ()).throw(AssertionError("R2 must not be called")))
    monkeypatch.setattr(salad_control, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Salad must not be called")))
    db.init_db()
    queue.save_setting("salad_active", {"image": "ghcr.io/test/worker:v1", "group_name": "test-group", "display_name": "Test"})
    db.save_workflow("axis3", "Axis 3 test", WORKFLOW, capability_spec=CAPABILITY_SPEC)


def variables(seed=7):
    return {
        "input.image_1": "s3://test-bucket/inputs/asset-1/reference.png",
        "prompt.positive": "A portrait",
        "prompt.negative": "blurry",
        "generation.seed": seed,
        "generation.steps": 8,
        "generation.cfg": 4.0,
        "generation.sampler": "euler",
        "generation.scheduler": "normal",
        "lora.style.name": "soft-style.safetensors",
        "lora.style.strength_model": 0.8,
        "lora.style.strength_clip": 0.6,
        "output.width": 512,
        "output.height": 768,
    }


def body(seed_mode="fixed", request_id="axis3-run"):
    wf = db.get_workflow("axis3")
    info = contracts.workflow_contract(wf)
    return {
        "contract_version": 1,
        "client_request_id": request_id,
        "workflow_id": "axis3",
        "workflow_version": info["workflow_version"],
        "capability_version": info["capability_version"],
        "seed_mode": seed_mode,
        "variables": variables(),
        "priority": "medium",
    }


def test_catalog_is_bound_to_actual_nodes_and_declared_limits():
    info = contracts.workflow_contract(db.get_workflow("axis3"))
    capabilities = info["capabilities"]
    assert capabilities["operation"] == "image_edit"
    assert capabilities["model"]["name"] == "Qwen Image Edit"
    assert capabilities["references"][0]["role"] == "identity"
    assert capabilities["supports_positive_prompt"]
    assert capabilities["supports_negative_prompt"]
    assert capabilities["seed_variable"] == "generation.seed"
    assert capabilities["supports_sampler"] and capabilities["supports_scheduler"]
    assert capabilities["outputs"][0]["media_type"] == "image"
    assert capabilities["workflow_summary"]["source"] == "saved_comfyui_api_graph"
    assert capabilities["loras"][0]["name_variable"] == "lora.style.name"
    assert {edge["to"] for edge in capabilities["workflow_summary"]["edges"]} == {"2", "3", "5", "6", "8"}


@pytest.mark.parametrize("key,value,code", [
    ("generation.steps", 60, "invalid_range"),
    ("generation.sampler", "unknown_sampler", "invalid_option"),
    ("lora.style.strength_model", 2.1, "invalid_range"),
    ("lora.style.strength_model", 0.805, "invalid_step"),
    ("output.width", 0, "invalid_range"),
])
def test_backend_rejects_settings_outside_the_saved_capability_contract(key, value, code):
    values = variables()
    values[key] = value
    with pytest.raises(contracts.ContractError) as error:
        contracts.validate_variables(WORKFLOW, values, CAPABILITY_SPEC)
    assert error.value.code == code
    assert error.value.path == "variables." + key


def test_credential_like_prompt_text_is_rejected_before_job_creation():
    values = variables()
    values["prompt.positive"] = "api_key: do-not-store-this"
    with pytest.raises(contracts.ContractError) as error:
        contracts.validate_variables(WORKFLOW, values, CAPABILITY_SPEC)
    assert error.value.code == "sensitive_value"


def test_catalog_spec_cannot_claim_unbound_inputs_or_reference_roles():
    bad = {**CAPABILITY_SPEC, "fields": {"generation.steps": {"kind": "integer"}, "generation.hidden": {"kind": "integer"}}}
    with pytest.raises(Exception) as error:
        contracts.validate_capability_spec(WORKFLOW, bad)
    assert getattr(error.value, "code", None) == "unbound_capability"


def test_reordered_generic_references_change_graph_bindings_and_snapshot_order():
    api_prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_1}}"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "{{input.image_2}}"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    spec = {"reference_inputs": [
        {"variable_key": "input.image_1", "role": "reference", "order": 0, "reorderable": True},
        {"variable_key": "input.image_2", "role": "reference", "order": 1, "reorderable": True},
    ]}
    wf = {"id": "two-refs", "api_prompt": api_prompt, "capability_spec": spec}
    capabilities = contracts.build_catalog(wf, contracts.digest(api_prompt))
    before = {
        "input.image_1": "s3://test-bucket/inputs/asset-a/a.png",
        "input.image_2": "s3://test-bucket/inputs/asset-b/b.png",
    }
    order = ["input.image_2", "input.image_1"]
    effective = contracts.reorder_reference_values(before, capabilities, order)
    assert effective["input.image_1"] == before["input.image_2"]
    assert effective["input.image_2"] == before["input.image_1"]
    snapshot = contracts.effective_snapshot(wf, effective, "medium", reference_order=order)
    assert snapshot["prompt"]["1"]["inputs"]["image"] == before["input.image_2"]
    assert snapshot["prompt"]["2"]["inputs"]["image"] == before["input.image_1"]
    assert [item["order"] for item in snapshot["references"]] == [0, 1]
    assert snapshot["reference_order"] == order

    db.save_workflow("two-refs", "Two generic references", api_prompt, capability_spec=spec)
    info = contracts.workflow_contract(db.get_workflow("two-refs"))
    accepted = controller.submit_job("two-refs", before, "medium", client_request_id="axis3-reference-order",
        workflow_version=info["workflow_version"], capability_version=info["capability_version"],
        reference_order=order)
    claim = queue.claim("two-refs-worker")
    assert claim["job_id"] == accepted["id"]
    assert claim["request"]["prompt"]["1"]["inputs"]["image"] == before["input.image_2"]
    assert claim["request"]["prompt"]["2"]["inputs"]["image"] == before["input.image_1"]
    assert accepted["snapshot"]["references"][0]["uri"] == before["input.image_2"]


def test_random_seed_resolves_once_is_snapshotted_and_reaches_worker_payload(monkeypatch):
    monkeypatch.setattr("app.main.random_seed", lambda minimum, maximum: maximum)
    request_body = body("random", "axis3-random")
    contract_request = contracts.JobIn.model_validate(request_body)
    accepted = controller.submit_job(contract_request.workflow_id, contract_request.variables,
        contract_request.priority, client_request_id=contract_request.client_request_id,
        workflow_version=contract_request.workflow_version, capability_version=contract_request.capability_version,
        seed_mode=contract_request.seed_mode, reference_order=contract_request.reference_order,
        source_job_id=contract_request.source_job_id)
    second = controller.submit_job(contract_request.workflow_id, contract_request.variables,
        contract_request.priority, client_request_id=contract_request.client_request_id,
        workflow_version=contract_request.workflow_version, capability_version=contract_request.capability_version,
        seed_mode=contract_request.seed_mode, reference_order=contract_request.reference_order,
        source_job_id=contract_request.source_job_id)
    assert second["id"] == accepted["id"]
    assert second["snapshot"]["seed"] == accepted["snapshot"]["seed"]

    snapshot = accepted["snapshot"]
    assert snapshot["seed"] == 1000000
    assert snapshot["seed_mode"] == "random"
    assert snapshot["positive_prompt"] == "A portrait"
    assert snapshot["negative_prompt"] == "blurry"
    assert snapshot["output_spec"]["width"] == 512
    assert snapshot["references"][0]["role"] == "identity"
    claim = queue.claim("axis3-worker")
    assert claim["request"]["prompt"]["6"]["inputs"]["seed"] == snapshot["seed"]
    assert claim["request"]["prompt"]["5"]["inputs"]["lora_name"] == "soft-style.safetensors"
    assert claim["request"]["prompt"]["5"]["inputs"]["strength_model"] == 0.8
    assert snapshot["loras"][0]["strength_clip"] == 0.6

    worker_path = Path(__file__).parents[1] / "salad-worker" / "pull_worker.py"
    spec = importlib.util.spec_from_file_location("axis3_worker", worker_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    forwarded = module.build_comfy_payload({"request": claim["request"]})
    assert forwarded == claim["request"]
    assert forwarded["prompt"]["6"]["inputs"]["sampler_name"] == "euler"
    unresolved = {"request": {"prompt": {"1": {"inputs": {"text": "{{prompt.negative}}"}}}}}
    with pytest.raises(RuntimeError, match="unresolved Workflow binding"):
        module.build_comfy_payload(unresolved)
