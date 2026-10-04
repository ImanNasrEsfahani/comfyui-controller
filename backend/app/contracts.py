"""PDF-43: versioned contracts adapted to the existing workflow variables API.

Only variables used by the saved API graph are effective. Capability discovery
describes bindings, not unverified node/model support or valid dimension ranges.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import urlparse
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import settings
from .template import ANY, render_template
from .workflow_catalog import build_catalog, validate_capability_spec


class ContractError(ValueError):
    def __init__(self, code, message, path="", status=422):
        super().__init__(message)
        self.code, self.path, self.status = code, path, status


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[1] = 1
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128,
                                        pattern=r"^[A-Za-z0-9._:-]+$")
    workflow_id: str = Field(min_length=1, max_length=80)
    workflow_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    capability_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    seed_mode: Literal["fixed", "random"] | None = None
    reference_order: list[str] | None = Field(default=None, max_length=32)
    variables: dict[str, Any] = Field(default_factory=dict)
    priority: str | None = None
    source_job_id: str | None = Field(default=None, max_length=80)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def placeholders(value):
    result = set()
    def walk(item):
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            result.update(ANY.findall(item))
    walk(value)
    return sorted(result)


SECRET_KEY = re.compile(r"(^|[._-])(token|secret|authorization|api[_-]?key|password)($|[._-])", re.I)
SECRET_ASSIGNMENT = re.compile(r"\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|password|authorization|bearer|token|secret)\s*[:=]\s*\S+", re.I)
JS_SAFE_INTEGER = (1 << 53) - 1


def ensure_no_credentials(value, path="variables"):
    secrets = [settings.internal_token, settings.salad_api_key,
               settings.r2_access_key_id, settings.r2_secret_access_key]
    import os
    secrets.append(os.getenv("DIRECT_WORKER_TOKEN", ""))

    def check(item, path):
        if isinstance(item, dict):
            for key, child in item.items():
                if SECRET_KEY.search(key):
                    raise ContractError("sensitive_field", "Credentials cannot be saved in a Job", path + "." + key)
                check(child, path + "." + key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                check(child, path + f".{index}")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ContractError("invalid_number", "A finite number is required", path)
        elif isinstance(item, str):
            if SECRET_ASSIGNMENT.search(item) or any(secret and len(secret) >= 8 and secret in item for secret in secrets):
                raise ContractError("sensitive_value", "Credentials cannot be saved in a Job", path)
    check(value, path)


def validate_variables(template, variables, capability_spec=None):
    keys = placeholders(template)
    ensure_no_credentials(variables)
    unknown = set(variables) - set(keys)
    if unknown:
        raise ContractError("unsupported_variable", "This field is not used by the saved workflow", "variables." + sorted(unknown)[0])
    declared_fields = capability_spec.get("fields", {}) if isinstance(capability_spec, dict) else {}
    optional_images = {
        item.get("variable_key") for item in (capability_spec or {}).get("reference_inputs", [])
        if isinstance(item, dict) and item.get("required") is False
    } if isinstance(capability_spec, dict) else set()
    for key in keys:
        if key not in variables:
            raise ContractError("missing_variable", "A required workflow field is missing", "variables." + key)
        value = variables[key]
        field = declared_fields.get(key, {}) if isinstance(declared_fields, dict) else {}
        if key.lower().endswith("enabled") and not isinstance(value, bool):
            raise ContractError("invalid_boolean", "A boolean is required", "variables." + key)
        if re.search(r"(seed|steps|width|height|count)$", key, re.I):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError("invalid_integer", "An integer is required", "variables." + key)
            if abs(value) > JS_SAFE_INTEGER:
                raise ContractError("invalid_range", "The integer is outside the range this form can represent safely", "variables." + key)
            if not key.lower().endswith("seed") and value <= 0:
                raise ContractError("invalid_range", "A positive integer is required", "variables." + key)
        elif re.search(r"(cfg|denoise|strength(?:_(?:model|clip))?|(?:model|clip)_strength)$", key, re.I):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ContractError("invalid_number", "A finite number is required", "variables." + key)
        if key.startswith("prompt.") and not isinstance(value, str):
            raise ContractError("invalid_prompt", "Prompt must be text", "variables." + key)
        if re.fullmatch(r"input\.image_\d+", key):
            if not isinstance(value, str):
                raise ContractError("invalid_reference", "An uploaded image reference is required", "variables." + key)
            if key not in optional_images and not value.strip():
                raise ContractError("missing_reference", "An input image is required", "variables." + key)
        if field:
            kind = field.get("kind")
            valid = (
                kind in {"prompt", "text", "select"} and isinstance(value, str) or
                kind == "boolean" and isinstance(value, bool) or
                kind == "integer" and isinstance(value, int) and not isinstance(value, bool) or
                kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            )
            if not valid:
                code = "invalid_boolean" if kind == "boolean" else "invalid_integer" if kind == "integer" else "invalid_number"
                raise ContractError(code, "Value does not match the Workflow field type", "variables." + key)
            if kind == "select" and value not in field.get("options", []):
                raise ContractError("invalid_option", "Choose a value supported by this Workflow", "variables." + key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum, maximum = field.get("minimum"), field.get("maximum")
                if minimum is not None and value < minimum or maximum is not None and value > maximum:
                    raise ContractError("invalid_range", "Value is outside the range supported by this Workflow", "variables." + key)
                step = field.get("step")
                if step is not None:
                    base = minimum if minimum is not None else 0
                    if not math.isclose((value - base) / step, round((value - base) / step), rel_tol=1e-9, abs_tol=1e-9):
                        raise ContractError("invalid_step", "Value does not match the step supported by this Workflow", "variables." + key)
                if key.lower().endswith("seed") and value < 0:
                    raise ContractError("invalid_range", "Seed must be zero or greater", "variables." + key)
    return dict(variables)


def validate_image_references(variables, optional_keys=()):
    """Require image bindings to resolve to this controller's uploaded assets.

    Legacy signed URLs for this bucket are normalized by submit_job before this
    check. Arbitrary remote URLs and non-input objects are never dispatched.
    """
    for key, value in variables.items():
        if not re.fullmatch(r"input\.image_\d+", key):
            continue
        if key in optional_keys and value == "":
            continue
        uri = urlparse(value) if isinstance(value, str) else None
        path = (uri.path or "").lstrip("/").split("/") if uri else []
        if (not uri or uri.scheme != "s3" or uri.netloc != settings.r2_bucket
                or len(path) < 3 or path[0] != "inputs" or not all(path[1:])
                or uri.query or uri.fragment or uri.username or uri.password):
            raise ContractError(
                "invalid_reference",
                "Upload this reference image through the controller before generating",
                "variables." + key,
            )
    return dict(variables)


def reorder_reference_values(variables, capabilities, reference_order):
    """Map the visible generic reference order onto stable graph-bound slots."""
    values = dict(variables)
    if reference_order is None:
        return values
    slots = capabilities.get("references", [])
    slots = sorted(slots, key=lambda item: (item.get("order", 0), item.get("variable_key", "")))
    expected = [slot.get("variable_key") for slot in slots]
    if (len(slots) < 2 or not all(slot.get("reorderable") and slot.get("role") == "reference" for slot in slots)
            or len(reference_order) != len(expected) or set(reference_order) != set(expected)
            or len(set(reference_order)) != len(reference_order)):
        raise ContractError("invalid_reference_order", "This Workflow does not allow that reference image order", "reference_order")
    source_values = {key: values.get(key) for key in expected}
    for index, target_key in enumerate(expected):
        values[target_key] = source_values[reference_order[index]]
    return values


def workflow_contract(wf):
    workflow_version = digest(wf["api_prompt"])
    capability_version = digest({"workflow_version": workflow_version,
                                 "capability_spec": wf.get("capability_spec")})
    capabilities = build_catalog(wf, workflow_version)
    capabilities["capability_version"] = capability_version
    return {"contract_version": 2, "workflow_version": workflow_version,
            "capability_version": capability_version, "tool_id": wf["id"],
            "variable_keys": placeholders(wf["api_prompt"]),
            "capabilities_source": "saved_comfyui_api_graph",
            "capabilities": capabilities}


def effective_snapshot(wf, variables, priority, *, client_request_id=None, seed_mode="fixed", reference_order=None):
    rendered = render_template(wf["api_prompt"], variables)
    wf_contract = workflow_contract(wf)
    capabilities = wf_contract["capabilities"]
    inputs = [(node.get("class_type", ""), node.get("inputs", {}))
              for node in rendered.values() if isinstance(node, dict)]
    models, loras = [], []
    def safe_name(value):
        if not isinstance(value, str):
            return value
        return value.replace("\\", "/").rsplit("/", 1)[-1]

    for kind, values in inputs:
        if not isinstance(values, dict):
            continue
        for key in ("ckpt_name", "unet_name", "clip_name", "vae_name"):
            if isinstance(values.get(key), str):
                models.append({"node_type": kind, "field": key, "name": safe_name(values[key]), "version": None})
        if "lora_name" in values:
            enabled = values.get("enabled", True)
            loras.append({"name": safe_name(values["lora_name"]),
                          "enabled": enabled if isinstance(enabled, bool) else None,
                          "active": enabled is not False,
                          "strength_model": values.get("strength_model"),
                          "strength_clip": values.get("strength_clip"), "version": None})
    references = []
    reference_slots = {item["variable_key"]: item for item in capabilities["references"]}
    canonical_order = sorted(reference_slots, key=lambda key: (reference_slots[key].get("order", 0), key))
    execution_order = reference_order if reference_order is not None else canonical_order
    execution_positions = {key: index for index, key in enumerate(canonical_order)}
    for key in sorted(variables, key=lambda k: int(k.rsplit("_", 1)[-1]) if re.fullmatch(r"input\.image_\d+", k) else 0):
        if not re.fullmatch(r"input\.image_\d+", key):
            continue
        value = variables[key]
        uri = urlparse(value)
        parts = uri.path.lstrip("/").split("/")
        asset_id = parts[1] if uri.scheme == "s3" and uri.netloc == settings.r2_bucket and len(parts) >= 3 and parts[0] == "inputs" else None
        slot = reference_slots.get(key, {})
        order = execution_positions.get(key, slot.get("order", len(references)))
        if reference_order is not None and key in canonical_order:
            # Values were remapped into graph slots before snapshot creation.
            order = canonical_order.index(key)
        references.append({"asset_id": asset_id, "role": slot.get("role", "reference"), "order": order,
                           "label": slot.get("label", key), "variable": key, "uri": value})
    references.sort(key=lambda item: item["order"])

    def resolved(name):
        explicit = variables.get("output." + name, variables.get("generation." + name))
        if explicit is not None:
            return explicit
        found = [v[name] for _, v in inputs if isinstance(v, dict) and name in v and isinstance(v[name], (int, float))]
        return found[0] if found and all(x == found[0] for x in found) else None

    return {"contract_version": 2, "workflow_id": wf["id"], **wf_contract,
            "client_request_id": client_request_id, "model_id": models[0]["name"] if len(models) == 1 else None,
            "operation": capabilities["operation"], "model": capabilities["model"],
            "models": models, "positive_prompt": variables.get("prompt.positive", variables.get("prompt.user")),
            "negative_prompt": variables.get("prompt.negative"), "variables": variables,
            "parameters": {k: v for k, v in variables.items() if not k.startswith(("prompt.", "input.image_"))},
            "references": references, "seed": resolved("seed"), "seed_mode": seed_mode, "loras": loras,
            "reference_order": execution_order,
            "output_spec": {"media_type": None, "width": resolved("width"), "height": resolved("height"),
                            "count": resolved("batch_size")},
            "validated_model_capabilities": None,
            "workflow_summary": capabilities["workflow_summary"],
            "priority": priority, "prompt": rendered}
