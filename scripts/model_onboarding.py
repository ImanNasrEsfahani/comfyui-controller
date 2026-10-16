#!/usr/bin/env python3
"""Safe legacy Workflow -> Phase07 draft-model onboarding.

Offline metadata reconciliation only: NEVER marks a model ready, approves an
image, changes a deployment, starts Salad, or publishes a Workflow. An exact
artifact checksum and license must be provided by the operator.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SHA = re.compile(r"^[a-f0-9]{64}$")
MODEL_CLASSES = frozenset({
    "CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader", "DiffusionModelLoader",
    "LoraLoader", "LoraLoaderModelOnly", "VAELoader", "CLIPLoader",
    "DualCLIPLoader", "TripleCLIPLoader", "ControlNetLoader",
})
IDENTITY_TABLES = frozenset({"workflows", "model_families", "model_versions", "model_artifacts"})
PRECISIONS = frozenset({"fp32", "fp16", "bf16", "fp8", "int8", "int4"})
MODALITIES = frozenset({"image", "video", "multimodal"})


def connect(path: Path, readonly: bool = True) -> sqlite3.Connection:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Expected a regular SQLite database file")
    c = sqlite3.connect(f"file:{path}?mode={'ro' if readonly else 'rw'}", uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def require_schema(c: sqlite3.Connection) -> set[str]:
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not IDENTITY_TABLES <= tables:
        raise ValueError("Required Phase07 migration missing: " + ", ".join(sorted(IDENTITY_TABLES - tables)))
    return tables


def safe_filename(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    if value.startswith("{{") or any(c in value for c in ("\n", "\r", "\x00", "?", "#")):
        return None
    # Only a basename, never any absolute location, URL, query string or token.
    result = value.replace("\\", "/").rsplit("/", 1)[-1]
    return result if re.fullmatch(r"[\w.() +\-]{1,160}", result) else None


def workflow_graph_observations(raw: object) -> list[dict]:
    try:
        graph = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(graph, dict):
        return []
    found = []
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        kind = node.get("class_type")
        if kind not in MODEL_CLASSES:
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        files = sorted({name for key, value in inputs.items()
                        if isinstance(key, str) and
                        ("name" in key.lower() or key.lower() in ("ckpt", "model"))
                        if (name := safe_filename(value))})
        found.append({"node_id": str(node_id)[:32], "class_type": kind,
                      "filenames": files})
    return sorted(found, key=lambda entry: (entry["class_type"], entry["node_id"]))


def inspect(c: sqlite3.Connection) -> dict:
    tables = require_schema(c)
    counts = {}
    for name in ("model_families", "model_versions", "worker_images", "deployment_profiles",
                 "image_model_compatibility", "model_deployment_compatibility",
                 "model_parameter_schemas"):
        if name in tables:
            counts[name] = int(c.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        else:
            counts[name] = None
    workflows = []
    for r in c.execute("SELECT id,name,api_prompt FROM workflows ORDER BY id"):
        workflows.append({"id": r["id"], "name": r["name"],
                          "loader_nodes": workflow_graph_observations(r["api_prompt"])})
    verified_tables = {
        "model_versions", "worker_images", "model_families", "image_model_compatibility",
        "deployment_profile_revisions", "deployment_profiles", "model_deployment_compatibility",
    }
    eligible = 0
    if verified_tables <= tables:
        eligible = int(c.execute("""SELECT COUNT(*) FROM model_versions v
            WHERE v.status='ready' AND EXISTS (
                SELECT 1 FROM image_model_compatibility ic
                JOIN worker_images wi ON wi.id=ic.image_id
                JOIN deployment_profile_revisions rev ON rev.image_id=wi.id
                JOIN deployment_profiles p ON p.active_revision_id=rev.id
                JOIN model_deployment_compatibility dc
                  ON dc.revision_id=rev.id AND dc.model_id=v.id
                WHERE ic.model_id=v.id AND ic.state='tested_pass'
                AND wi.signature_status='verified' AND wi.status='approved'
                AND rev.status='active' AND dc.state='tested_pass')""").fetchone()[0])
    return {
        "format": "comfyui-registry-onboarding-v1",
        "workflows_count": len(workflows), "workflows": workflows, "counts": counts,
        "catalog_eligible_count": eligible, "catalog_eligible": eligible > 0,
        "warning": "Rows and file names are NOT runtime verification; a model remains hidden until trusted Worker/Image/deployment attestations exist.",
    }


def blank_manifest(report: dict) -> dict:
    return {
        "format": "comfyui-model-draft-import-v1",
        "models": [],
        "workflow_candidates": [{"workflow_id": w["id"], "workflow_name": w["name"],
                                 "loader_nodes": w["loader_nodes"]}
                                for w in report["workflows"]],
        "instructions": "Manually populate models[] using real model weight SHA256, an approved license and VRAM. Never claim Runtime verified from a Workflow filename.",
        "example_model_entry": {
            "family": {"name": "REPLACE_WITH_ACTUAL_MODEL", "vendor": "REPLACE_WITH_VENDOR",
                       "modality": "image", "description": ""},
            "model": {"revision": "REPLACE_WITH_REVISION", "license_id": "REPLACE_WITH_LICENSE",
                      "artifact_sha256": "REPLACE_WITH_REAL_64_DIGIT_SHA256",
                      "precision": "fp8", "vram_gb": 24,
                      "capabilities": {}},
        },
    }


def validate_manifest(data: object) -> list[tuple[dict, dict]]:
    if not isinstance(data, dict) or data.get("format") != "comfyui-model-draft-import-v1":
        raise ValueError("Invalid draft import format")
    models = data.get("models")
    if not isinstance(models, list) or not 1 <= len(models) <= 100:
        raise ValueError("models must contain 1..100 reviewed entries")
    validated = []
    for entry in models:
        if not isinstance(entry, dict) or not isinstance(entry.get("family"), dict) or not isinstance(entry.get("model"), dict):
            raise ValueError("Each model entry needs family and model objects")
        family, model = entry["family"], entry["model"]
        for key in ("name", "vendor"):
            if not isinstance(family.get(key), str) or not 1 <= len(family[key].strip()) <= 120:
                raise ValueError("Invalid family " + key)
        if family.get("modality") not in MODALITIES:
            raise ValueError("Invalid model modality")
        desc = family.get("description", "")
        if not isinstance(desc, str) or len(desc) > 500:
            raise ValueError("Invalid description")
        if not isinstance(model.get("revision"), str) or not 1 <= len(model["revision"]) <= 100:
            raise ValueError("Invalid model revision")
        if not isinstance(model.get("license_id"), str) or not re.fullmatch(r"[A-Za-z0-9 .:+/_\-]{2,120}", model["license_id"]):
            raise ValueError("Invalid model license; obtain a real license, never guess")
        if not isinstance(model.get("artifact_sha256"), str) or not SHA.fullmatch(model["artifact_sha256"]):
            raise ValueError("Invalid model artifact sha256; no fake or placeholder hashes")
        if model["artifact_sha256"] == "0" * 64:
            raise ValueError("Placeholder SHA256 is forbidden")
        if model.get("precision") not in PRECISIONS:
            raise ValueError("Unknown precision")
        vram = model.get("vram_gb")
        if type(vram) is not int or not 1 <= vram <= 512:
            raise ValueError("VRAM must be an integer from 1 to 512")
        capabilities = model.get("capabilities", {})
        packed = json.dumps(capabilities, ensure_ascii=False, sort_keys=True)
        if not isinstance(capabilities, dict) or len(packed) > 10_000 or any(
                token in packed.lower() for token in ("secret", "password", "token", "vault://", "s3://")):
            raise ValueError("Invalid/unsafe capabilities")
        validated.append((family, model))
    return validated


def backup_database(source: Path, backup: Path) -> None:
    source = source.resolve(strict=True)
    backup = backup.expanduser().resolve()
    if backup.exists() or source == backup or not backup.parent.is_dir():
        raise ValueError("Backup path must be NEW, outside the source and in an existing directory")
    with connect(source) as original:
        with sqlite3.connect(str(backup)) as dest:
            original.backup(dest)
            if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite backup integrity check failed")
    os.chmod(backup, 0o600)


def import_drafts(path: Path, data: dict, backup: Path) -> dict:
    validated = validate_manifest(data)
    # Backup is performed BEFORE any write and never overwritten.
    with connect(path) as c:
        require_schema(c)
        if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Source database failed quick_check")
    backup_database(path, backup)
    results = []
    with connect(path, readonly=False) as c:
        c.execute("BEGIN IMMEDIATE")
        for f, m in validated:
            name, vendor, modality = f["name"].strip(), f["vendor"].strip(), f["modality"]
            fam = c.execute("SELECT id,vendor,modality FROM model_families WHERE name=?", (name,)).fetchall()
            if len(fam) > 1 or (fam and (fam[0]["vendor"] != vendor or fam[0]["modality"] != modality)):
                raise ValueError("Existing model family conflicts: " + name)
            if fam:
                family_id = fam[0]["id"]
            else:
                family_id = str(uuid4())
                c.execute("INSERT INTO model_families(id,name,vendor,modality,description,created_at) VALUES(?,?,?,?,?,?)",
                          (family_id, name, vendor, modality, f.get("description", ""), datetime.now(timezone.utc).isoformat()))
            revision = m["revision"]
            existing = c.execute("SELECT id,artifact_sha256,license_id,precision,vram_gb FROM model_versions WHERE family_id=? AND revision=?", (family_id, revision)).fetchone()
            if existing:
                if any(existing[k] != m[k] for k in ("artifact_sha256", "license_id", "precision", "vram_gb")):
                    raise ValueError("Existing model revision has different immutable metadata: " + name)
                model_id = existing["id"]
                operation = "unchanged"
            else:
                model_id = str(uuid4())
                c.execute("""INSERT INTO model_versions
                    (id,family_id,revision,license_id,artifact_sha256,precision,vram_gb,capabilities_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (model_id, family_id, revision, m["license_id"], m["artifact_sha256"], m["precision"],
                     m["vram_gb"], json.dumps(m.get("capabilities", {}), sort_keys=True),
                     datetime.now(timezone.utc).isoformat()))
                operation = "created_draft"
            results.append({"family": name, "revision": revision, "model_id": model_id, "result": operation})
        # db connection context manager commits when no exception; no fake ready or compatibility states.
    return {"backup": str(backup), "models": results,
            "runtime_verified": False, "catalog_visible": False,
            "next": "Verify OCI signature, artifact SHA, Worker runtime and model/deployment compatibility in the trust pipeline."}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, required=True, help="SQLite database, usually the backend DB_PATH")
    p.add_argument("--report", type=Path, help="Write read-only JSON report")
    p.add_argument("--template", type=Path, help="Write a JSON manifest template")
    p.add_argument("--manifest", type=Path, help="Reviewed manifest, required with --import-drafts")
    p.add_argument("--import-drafts", action="store_true", help="Create draft only; never publish")
    p.add_argument("--backup", type=Path, help="NEW backup file required for imports")
    args = p.parse_args(argv)
    try:
        if args.import_drafts:
            if not args.manifest or not args.backup:
                raise ValueError("--manifest and --backup are mandatory for --import-drafts")
            result = import_drafts(args.db, json.loads(args.manifest.read_text(encoding="utf-8")), args.backup)
        else:
            if args.manifest or args.backup:
                raise ValueError("Do not supply --manifest/--backup without --import-drafts")
            with connect(args.db) as db:
                result = inspect(db)
            if args.template:
                if args.template.exists():
                    raise ValueError("Refusing to overwrite an existing template")
                args.template.write_text(json.dumps(blank_manifest(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.report:
            if args.report.exists():
                raise ValueError("Refusing to overwrite existing report")
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, json.JSONDecodeError) as e:
        print("SAFE STOP: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
