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
        elif isinstance(item, str) and any(secret and len(secret) >= 8 and secret in item for secret in secrets):
            raise ContractError("sensitive_value", "Credentials cannot be saved in a Job", path)
    check(value, path)


def validate_variables(template, variables):
    keys = placeholders(template)
    ensure_no_credentials(variables)
    unknown = set(variables) - set(keys)
    if unknown:
        raise ContractError("unsupported_variable", "This field is not used by the saved workflow", "variables." + sorted(unknown)[0])
    for key in keys:
        if key not in variables:
            raise ContractError("missing_variable", "A required workflow field is missing", "variables." + key)
        value = variables[key]
        if key.lower().endswith("enabled") and not isinstance(value, bool):
            raise ContractError("invalid_boolean", "A boolean is required", "variables." + key)
        if re.search(r"(seed|steps|width|height|count)$", key, re.I):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ContractError("invalid_integer", "An integer is required", "variables." + key)
            if not key.lower().endswith("seed") and value <= 0:
                raise ContractError("invalid_range", "A positive integer is required", "variables." + key)
        elif re.search(r"(cfg|denoise|strength)$", key, re.I):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractError("invalid_number", "A finite number is required", "variables." + key)
        if key.startswith("prompt.") and not isinstance(value, str):
            raise ContractError("invalid_prompt", "Prompt must be text", "variables." + key)
        if re.fullmatch(r"input\.image_\d+", key) and (not isinstance(value, str) or not value.strip()):
            raise ContractError("missing_reference", "An input image is required", "variables." + key)
    return dict(variables)


def workflow_contract(wf):
    return {"contract_version": 1, "workflow_version": digest(wf["api_prompt"]),
            "tool_id": wf["id"], "variable_keys": placeholders(wf["api_prompt"]),
            "capabilities_source": "saved_workflow_bindings",
            "validated_model_capabilities": None}


def effective_snapshot(wf, variables, priority, *, client_request_id=None):
    rendered = render_template(wf["api_prompt"], variables)
    inputs = [(node.get("class_type", ""), node.get("inputs", {}))
              for node in rendered.values() if isinstance(node, dict)]
    models, loras = [], []
    for kind, values in inputs:
        if not isinstance(values, dict):
            continue
        for key in ("ckpt_name", "unet_name", "clip_name", "vae_name"):
            if isinstance(values.get(key), str):
                models.append({"node_type": kind, "field": key, "name": values[key], "version": None})
        if "lora_name" in values:
            loras.append({"name": values["lora_name"], "strength_model": values.get("strength_model"),
                          "strength_clip": values.get("strength_clip"), "version": None})
    references = []
    for key in sorted(variables, key=lambda k: int(k.rsplit("_", 1)[-1]) if re.fullmatch(r"input\.image_\d+", k) else 0):
        if not re.fullmatch(r"input\.image_\d+", key):
            continue
        value = variables[key]
        uri = urlparse(value)
        parts = uri.path.lstrip("/").split("/")
        asset_id = parts[1] if uri.scheme == "s3" and uri.netloc == settings.r2_bucket and len(parts) >= 3 and parts[0] == "inputs" else None
        references.append({"asset_id": asset_id, "role": "reference", "order": len(references),
                           "variable": key, "uri": value})

    def resolved(name):
        explicit = variables.get("output." + name, variables.get("generation." + name))
        if explicit is not None:
            return explicit
        found = [v[name] for _, v in inputs if isinstance(v, dict) and name in v and isinstance(v[name], (int, float))]
        return found[0] if found and all(x == found[0] for x in found) else None

    return {"contract_version": 1, "workflow_id": wf["id"], **workflow_contract(wf),
            "client_request_id": client_request_id, "model_id": models[0]["name"] if len(models) == 1 else None,
            "models": models, "positive_prompt": variables.get("prompt.positive", variables.get("prompt.user")),
            "negative_prompt": variables.get("prompt.negative"), "variables": variables,
            "parameters": {k: v for k, v in variables.items() if not k.startswith(("prompt.", "input.image_"))},
            "references": references, "seed": resolved("seed"), "loras": loras,
            "output_spec": {"media_type": None, "width": resolved("width"), "height": resolved("height"),
                            "count": resolved("batch_size")},
            "priority": priority, "prompt": rendered}
