"""Capability catalog derived from the saved ComfyUI graph.

Only bindings present in the API graph can become runtime controls. Optional
labels, ranges, enumerations and reference roles are accepted as an explicit
workflow capability spec and are checked against those bindings.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_.:-]+)\}\}")
IMAGE_KEY = re.compile(r"^input\.image_(\d+)$")
INTEGER_KEY = re.compile(r"(seed|steps|width|height|count)$", re.I)
NUMBER_KEY = re.compile(r"(cfg|denoise|strength(?:_(?:model|clip))?|(?:model|clip)_strength)$", re.I)
SECRET_TEXT = re.compile(r"token|secret|password|authorization|api[_-]?key", re.I)

OPERATIONS = {"image_generation", "image_edit", "video_generation"}
FIELD_KINDS = {"prompt", "text", "integer", "number", "boolean", "select"}
REFERENCE_ROLES = {"reference", "identity", "clothing", "pose", "background", "style", "mask"}
FIELD_KEYS = {"label", "kind", "description", "default", "minimum", "maximum", "step", "options", "advanced"}
SPEC_KEYS = {"schema_version", "operation", "model", "fields", "reference_inputs"}


class CatalogError(ValueError):
    def __init__(self, code: str, message: str, path: str = "capability_spec"):
        super().__init__(message)
        self.code = code
        self.path = path


def _nodes(api_prompt: Any) -> dict[str, dict]:
    if not isinstance(api_prompt, dict):
        return {}
    return {str(node_id): node for node_id, node in api_prompt.items()
            if isinstance(node, dict) and isinstance(node.get("inputs", {}), dict)}


def _placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(_placeholders(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_placeholders(child))
    elif isinstance(value, str):
        found.update(PLACEHOLDER.findall(value))
    return found


def _bindings(api_prompt: Any) -> dict[str, list[dict[str, str]]]:
    found: dict[str, list[dict[str, str]]] = {}
    for node_id, node in _nodes(api_prompt).items():
        for input_name, value in node.get("inputs", {}).items():
            if not isinstance(value, str):
                continue
            for key in PLACEHOLDER.findall(value):
                found.setdefault(key, []).append({
                    "node_id": node_id,
                    "node_type": str(node.get("class_type", "unknown"))[:120],
                    "input": str(input_name)[:120],
                })
    return found


def _ui_titles(ui_workflow: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(ui_workflow, dict):
        return result
    nodes = ui_workflow.get("nodes")
    if not isinstance(nodes, list):
        return result
    for node in nodes:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        title = node.get("title") or (node.get("properties") or {}).get("Node name for S&R")
        title = _safe_text(title, "")
        if title:
            result[str(node["id"])] = title
    return result


def _safe_text(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if not value or SECRET_TEXT.search(value):
        return fallback
    value = value.replace("\\", "/").rsplit("/", 1)[-1]
    return value[:120] or fallback


def _input_role(title: str, key: str) -> str:
    source = f"{title} {key}".lower()
    for word, role in (("identity", "identity"), ("face", "identity"),
                       ("clothing", "clothing"), ("outfit", "clothing"),
                       ("pose", "pose"), ("background", "background"),
                       ("style", "style"), ("mask", "mask")):
        if word in source:
            return role
    return "reference"


def _class_category(node_type: str) -> str:
    name = node_type.lower()
    if "savevideo" in name or "videocombine" in name or "save_video" in name:
        return "output_video"
    if "saveimage" in name or "previewimage" in name or "imageoutput" in name:
        return "output_image"
    if "loadvideo" in name or "video" in name and "load" in name:
        return "video_input"
    if "loadimage" in name or "imageinput" in name:
        return "image_input"
    if "lora" in name:
        return "lora"
    if any(word in name for word in ("checkpointloader", "unetloader", "cliploader", "vaeloader", "model_loader")):
        return "model"
    if "ksampler" in name or "sampler" in name:
        return "sampler"
    if "cliptextencode" in name or "textencode" in name or "prompt" in name:
        return "prompt"
    if any(word in name for word in ("latent", "vae", "decode", "encode", "upscale", "resize", "crop", "mask")):
        return "processing"
    return "processing"


def _field_kind(key: str, spec: dict | None) -> str:
    if spec and spec.get("kind") in FIELD_KINDS:
        return spec["kind"]
    if key.startswith("prompt."):
        return "prompt"
    if key.lower().endswith("enabled"):
        return "boolean"
    if INTEGER_KEY.search(key):
        return "integer"
    if NUMBER_KEY.search(key):
        return "number"
    return "text"


def _friendly(key: str) -> str:
    image = IMAGE_KEY.match(key)
    if image:
        return f"Image reference {image.group(1)}"
    known = {
        "prompt.user": "Positive prompt",
        "prompt.positive": "Positive prompt",
        "prompt.negative": "Negative prompt",
        "generation.seed": "Seed",
        "generation.steps": "Steps",
        "generation.cfg": "CFG",
        "generation.sampler": "Sampler",
        "generation.scheduler": "Scheduler",
        "output.width": "Output width",
        "output.height": "Output height",
    }
    if key in known:
        return known[key]
    return re.sub(r"[._:-]+", " ", key).strip().title()[:120]


def validate_capability_spec(api_prompt: Any, spec: Any) -> dict | None:
    """Validate the optional UX metadata against real API-format placeholders."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - SPEC_KEYS:
        raise CatalogError("invalid_capability_spec", "Capability metadata has unknown or invalid fields")
    if spec.get("schema_version", 1) != 1:
        raise CatalogError("unsupported_capability_schema", "Only capability schema version 1 is supported")
    keys = _placeholders(api_prompt)
    bindings = _bindings(api_prompt)
    fields = spec.get("fields", {})
    if not isinstance(fields, dict):
        raise CatalogError("invalid_capability_fields", "Capability fields must be an object", "capability_spec.fields")
    for key, field in fields.items():
        path = f"capability_spec.fields.{key}"
        if key not in keys:
            raise CatalogError("unbound_capability", "A configured field is not used by this saved Workflow", path)
        if not isinstance(field, dict) or set(field) - FIELD_KEYS:
            raise CatalogError("invalid_capability_field", "A field definition has unknown or invalid properties", path)
        if not isinstance(field.get("kind"), str) or field.get("kind") not in FIELD_KINDS:
            raise CatalogError("invalid_capability_kind", "A supported field kind is required", path + ".kind")
        for prop in ("minimum", "maximum", "step"):
            value = field.get(prop)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise CatalogError("invalid_capability_range", "Range values must be finite numbers", path + "." + prop)
            if field.get("kind") == "integer" and value is not None and not float(value).is_integer():
                raise CatalogError("invalid_capability_range", "Integer fields need whole-number ranges and steps", path + "." + prop)
            if field.get("kind") == "integer" and value is not None and abs(value) > (1 << 53) - 1:
                raise CatalogError("invalid_capability_range", "Integer range exceeds the safe form limit", path + "." + prop)
        if field.get("minimum") is not None and field.get("maximum") is not None and field["minimum"] > field["maximum"]:
            raise CatalogError("invalid_capability_range", "Minimum cannot exceed maximum", path)
        if key.lower().endswith("seed") and field.get("kind") in {"integer", "number"}:
            if field.get("minimum") is not None and field["minimum"] < 0:
                raise CatalogError("invalid_capability_range", "Seed range cannot be negative", path + ".minimum")
            if field.get("maximum") is not None and field["maximum"] < 0:
                raise CatalogError("invalid_capability_range", "Seed range cannot be negative", path + ".maximum")
        if field.get("step") is not None and field["step"] <= 0:
            raise CatalogError("invalid_capability_range", "Step must be greater than zero", path + ".step")
        if field.get("kind") == "select":
            options = field.get("options")
            if not isinstance(options, list) or not options or any(not isinstance(v, str) or not v for v in options):
                raise CatalogError("invalid_capability_options", "Select fields need a non-empty list of valid options", path + ".options")
            if len(set(options)) != len(options):
                raise CatalogError("invalid_capability_options", "Select options must be unique", path + ".options")
        elif field.get("options") is not None:
            raise CatalogError("invalid_capability_options", "Only select fields may declare options", path + ".options")
        label = field.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip() or len(label) > 100):
            raise CatalogError("invalid_capability_label", "Field labels must be 1–100 characters", path + ".label")
        if field.get("description") is not None and (not isinstance(field["description"], str) or len(field["description"]) > 300):
            raise CatalogError("invalid_capability_description", "Descriptions may be at most 300 characters", path + ".description")
        if field.get("advanced") is not None and not isinstance(field["advanced"], bool):
            raise CatalogError("invalid_capability_advanced", "Advanced must be a boolean", path + ".advanced")
        if "default" in field:
            default = field["default"]
            kind = field["kind"]
            valid = ((kind in {"prompt", "text", "select"} and isinstance(default, str)) or
                     (kind == "boolean" and isinstance(default, bool)) or
                     (kind == "integer" and isinstance(default, int) and not isinstance(default, bool)) or
                     (kind == "number" and isinstance(default, (int, float)) and not isinstance(default, bool) and math.isfinite(default)))
            if not valid:
                raise CatalogError("invalid_capability_default", "Default value does not match its field kind", path + ".default")
            if kind == "select" and default not in field.get("options", []):
                raise CatalogError("invalid_capability_default", "Select default must be one of its options", path + ".default")
            if kind in {"integer", "number"} and field.get("minimum") is not None and default < field["minimum"]:
                raise CatalogError("invalid_capability_default", "Default is below the minimum", path + ".default")
            if kind in {"integer", "number"} and field.get("maximum") is not None and default > field["maximum"]:
                raise CatalogError("invalid_capability_default", "Default is above the maximum", path + ".default")
            if kind == "integer" and abs(default) > (1 << 53) - 1:
                raise CatalogError("invalid_capability_default", "Integer default exceeds the safe form limit", path + ".default")
            if key.lower().endswith("seed") and kind in {"integer", "number"} and default < 0:
                raise CatalogError("invalid_capability_default", "Seed defaults cannot be negative", path + ".default")
            if kind in {"integer", "number"} and field.get("step") is not None:
                base = field.get("minimum", 0)
                steps = (default - base) / field["step"]
                if not math.isclose(steps, round(steps), rel_tol=1e-9, abs_tol=1e-9):
                    raise CatalogError("invalid_capability_default", "Default does not match the declared step", path + ".default")

    operation = spec.get("operation")
    if operation is not None and (not isinstance(operation, str) or operation not in OPERATIONS):
        raise CatalogError("invalid_operation", "Operation must be image_generation, image_edit or video_generation", "capability_spec.operation")
    model = spec.get("model")
    if model is not None:
        if not isinstance(model, dict) or set(model) - {"id", "label", "version"}:
            raise CatalogError("invalid_model_metadata", "Model metadata may contain id, label and version", "capability_spec.model")
        for prop in ("id", "label", "version"):
            value = model.get(prop)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 120):
                raise CatalogError("invalid_model_metadata", "Model metadata values must be non-empty text", f"capability_spec.model.{prop}")
    references = spec.get("reference_inputs", [])
    if not isinstance(references, list):
        raise CatalogError("invalid_reference_metadata", "Reference inputs must be a list", "capability_spec.reference_inputs")
    used = set()
    for index, item in enumerate(references):
        path = f"capability_spec.reference_inputs.{index}"
        if not isinstance(item, dict) or set(item) - {"variable_key", "label", "role", "order", "required", "reorderable"}:
            raise CatalogError("invalid_reference_metadata", "Reference entry has unknown or invalid properties", path)
        key = item.get("variable_key")
        if not isinstance(key, str) or not IMAGE_KEY.match(key) or key not in keys or key in used:
            raise CatalogError("unbound_reference", "Reference input must use a unique image placeholder in the Workflow", path + ".variable_key")
        if not any(binding["input"].lower() in {"image", "images", "image_1", "image_2"} and
                   "loadimage" in binding["node_type"].lower() for binding in bindings.get(key, [])):
            raise CatalogError("invalid_reference_binding", "Reference metadata must map to an actual LoadImage input", path + ".variable_key")
        used.add(key)
        if item.get("role") is not None and (not isinstance(item["role"], str) or item["role"] not in REFERENCE_ROLES):
            raise CatalogError("invalid_reference_role", "Reference role is not supported", path + ".role")
        if item.get("order") is not None and (isinstance(item["order"], bool) or not isinstance(item["order"], int) or item["order"] < 0):
            raise CatalogError("invalid_reference_order", "Reference order must be a non-negative integer", path + ".order")
        for prop in ("required", "reorderable"):
            if item.get(prop) is not None and not isinstance(item[prop], bool):
                raise CatalogError("invalid_reference_metadata", f"{prop} must be a boolean", path + "." + prop)
        if item.get("label") is not None and (not isinstance(item["label"], str) or not item["label"].strip() or len(item["label"]) > 100):
            raise CatalogError("invalid_reference_label", "Reference labels must be 1–100 characters", path + ".label")
        if item.get("reorderable") and item.get("role", "reference") != "reference":
            raise CatalogError("invalid_reference_metadata", "Only generic reference slots can be reordered safely", path + ".reorderable")
    return spec


def _connections(nodes: dict[str, dict]) -> list[dict[str, str]]:
    edges = []
    for target_id, node in nodes.items():
        for input_name, value in node.get("inputs", {}).items():
            if (isinstance(value, list) and len(value) == 2 and
                    isinstance(value[0], (str, int)) and isinstance(value[1], int)):
                source_id = str(value[0])
                if source_id in nodes:
                    edges.append({"from": source_id, "to": target_id, "input": str(input_name)[:80]})
    return edges


def build_catalog(wf: dict, workflow_version: str) -> dict:
    api_prompt = wf.get("api_prompt") or {}
    nodes = _nodes(api_prompt)
    bindings = _bindings(api_prompt)
    keys = sorted(_placeholders(api_prompt))
    spec = wf.get("capability_spec") if isinstance(wf.get("capability_spec"), dict) else {}
    declared_fields = spec.get("fields", {}) if isinstance(spec.get("fields"), dict) else {}
    titles = _ui_titles(wf.get("ui_workflow"))

    reference_meta = {item["variable_key"]: item for item in spec.get("reference_inputs", [])
                      if isinstance(item, dict) and isinstance(item.get("variable_key"), str)}
    references = []
    for key in keys:
        match = IMAGE_KEY.match(key)
        if not match:
            continue
        image_binding = next((b for b in bindings.get(key, [])
                              if "loadimage" in b["node_type"].lower()), None)
        meta = reference_meta.get(key, {})
        if image_binding is None and meta:
            # Invalid declarations are rejected on save; keep reads safe if an
            # old database row predates that validation.
            continue
        title = titles.get(image_binding["node_id"], "") if image_binding else ""
        references.append({
            "variable_key": key,
            "label": meta.get("label") or title or f"Image reference {match.group(1)}",
            "role": meta.get("role") or _input_role(title, key),
            "order": meta.get("order", int(match.group(1)) - 1),
            "required": meta.get("required", True),
            "reorderable": meta.get("reorderable", False),
            "bindings": bindings.get(key, []),
        })
    references.sort(key=lambda item: (item["order"], item["variable_key"]))

    fields = []
    for key in keys:
        definition = declared_fields.get(key, {})
        if not isinstance(definition, dict):
            definition = {}
        bindings_for_key = bindings.get(key, [])
        if IMAGE_KEY.match(key):
            continue
        fields.append({
            "variable_key": key,
            "label": definition.get("label") or _friendly(key),
            "kind": _field_kind(key, definition),
            "description": definition.get("description", ""),
            "default": definition.get("default"),
            "minimum": definition.get("minimum"),
            "maximum": definition.get("maximum"),
            "step": definition.get("step"),
            "options": definition.get("options", []),
            "advanced": definition.get("advanced", bool(re.search(r"(steps|cfg|sampler|scheduler|seed|denoise|strength|width|height|lora)", key, re.I))),
            "required": True,
            "bindings": bindings_for_key,
        })

    image_outputs, video_outputs = [], []
    model_nodes, lora_nodes = [], []
    summary_nodes = []
    for node_id, node in nodes.items():
        node_type = str(node.get("class_type", "unknown"))[:120]
        category = _class_category(node_type)
        inputs = node.get("inputs", {})
        label = titles.get(node_id) or node_type
        if category == "model":
            names = []
            if isinstance(inputs, dict):
                for name in ("ckpt_name", "unet_name", "model_name", "clip_name", "vae_name"):
                    value = inputs.get(name)
                    if isinstance(value, str) and not PLACEHOLDER.search(value):
                        names.append(os.path.basename(value.replace("\\", "/")))
            model_nodes.append({"node_id": node_id, "node_type": node_type, "label": label,
                                "names": names, "configured": bool(names)})
        elif category == "lora":
            values = inputs if isinstance(inputs, dict) else {}
            lora_name = values.get("lora_name")
            lora_nodes.append({
                "node_id": node_id,
                "name": os.path.basename(lora_name.replace("\\", "/")) if isinstance(lora_name, str) and not PLACEHOLDER.search(lora_name) else None,
                "name_variable": next(iter(PLACEHOLDER.findall(lora_name)), None) if isinstance(lora_name, str) else None,
                "strength_model_variable": next(iter(PLACEHOLDER.findall(str(values.get("strength_model", "")))), None),
                "strength_clip_variable": next(iter(PLACEHOLDER.findall(str(values.get("strength_clip", "")))), None),
                "status": "configurable" if any(PLACEHOLDER.search(str(v)) for v in values.values()) else "fixed",
            })
        if category == "output_image":
            image_outputs.append({"node_id": node_id, "node_type": node_type, "label": label, "media_type": "image"})
        if category == "output_video":
            video_outputs.append({"node_id": node_id, "node_type": node_type, "label": label, "media_type": "video"})
        summary_nodes.append({"node_id": node_id, "node_type": node_type, "label": label, "category": category})

    operation = spec.get("operation")
    if not operation:
        if video_outputs or any("video" in str(n.get("class_type", "")).lower() for n in nodes.values()):
            operation = "video_generation"
        elif references:
            operation = "image_edit"
        else:
            operation = "image_generation"

    model_spec = spec.get("model") if isinstance(spec.get("model"), dict) else {}
    model_names = [name for node in model_nodes for name in node["names"]]
    model = {
        "id": _safe_text(model_spec.get("id"), "") or None,
        "name": _safe_text(model_spec.get("label"), model_names[0] if len(model_names) == 1 else "") or None,
        "version": _safe_text(model_spec.get("version"), "") or None,
        "availability": "configured_unverified" if model_nodes else "unknown",
        "loader_nodes": model_nodes,
    }
    outputs = image_outputs + video_outputs
    seed_field = next((field for field in fields
                          if re.search(r"seed$", field["variable_key"], re.I) and
                          any("seed" in b["input"].lower() and "sampler" in b["node_type"].lower()
                              for b in field["bindings"])), None)
    inferred_seed = seed_field["variable_key"] if seed_field else None
    visible_fields = [{k: v for k, v in field.items() if k != "bindings"} for field in fields]
    summary_fields = []
    for field in visible_fields:
        summary_field = {k: v for k, v in field.items() if k not in {"default", "options"}}
        if field.get("options"):
            summary_field["option_count"] = len(field["options"])
        summary_fields.append(summary_field)
    summary = {
        "available": bool(nodes),
        "source": "saved_comfyui_api_graph",
        "workflow_version": workflow_version,
        "inputs": [{"variable_key": f["variable_key"], "label": f["label"], "role": f["role"], "order": f["order"]} for f in references]
                  + [{"variable_key": f["variable_key"], "label": f["label"], "role": "prompt"} for f in fields if f["kind"] == "prompt"],
        "model": {k: model[k] for k in ("id", "name", "version", "availability")},
        "parameters": summary_fields,
        "loras": lora_nodes,
        "processing": [n for n in summary_nodes if n["category"] not in {"image_input", "output_image", "output_video", "model", "lora"}],
        "outputs": outputs,
        "nodes": summary_nodes,
        "edges": _connections(nodes),
    }
    return {
        "schema_version": 1,
        "workflow_id": wf.get("id"),
        "workflow_version": workflow_version,
        "capability_version": None,
        "operation": operation,
        "model": model,
        "references": references,
        "fields": visible_fields,
        "bindings": bindings,
        "supports_positive_prompt": any(f["variable_key"] in {"prompt.positive", "prompt.user"} and f["kind"] == "prompt" for f in fields),
        "supports_negative_prompt": any(f["variable_key"] == "prompt.negative" and f["kind"] == "prompt" for f in fields),
        "seed_variable": inferred_seed,
        "seed_range": ({"minimum": max(0, seed_field["minimum"] if seed_field["minimum"] is not None else 0),
                        "maximum": min((1 << 53) - 1, seed_field["maximum"] if seed_field["maximum"] is not None else (1 << 53) - 1)}
                       if inferred_seed else None),
        "supports_dimensions": any(f["variable_key"].lower().endswith(("width", "height")) for f in fields),
        "supports_sampler": any(any("sampler" in b["input"].lower() for b in f["bindings"]) for f in fields),
        "supports_scheduler": any(any("scheduler" in b["input"].lower() for b in f["bindings"]) for f in fields),
        "loras": lora_nodes,
        "outputs": outputs,
        "workflow_summary": summary,
        "availability": "configured_unverified" if nodes else "unavailable",
    }
