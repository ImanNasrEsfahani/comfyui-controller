#!/usr/bin/env python3
"""Deterministic source patch: Salad image caching + safe cold-start telemetry.

Run from the project root AFTER extracting this patch package. It only changes
local files. It never calls Salad, GitHub, Docker or the project backend.
"""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
import re
import sys

MARKER = 'SALAD_IMAGE_CACHING'


def exact_replace(text: str, old: str, new: str, expected: int, label: str) -> str:
    n = text.count(old)
    if n != expected:
        raise ValueError(f'{label}: expected {expected} original anchors, got {n}; refusing to guess')
    return text.replace(old, new)


def caching_function() -> str:
    return '''def image_caching_enabled():
    """Explicit Salad OCI caching policy (new groups default to enabled)."""
    value = os.environ.get("SALAD_IMAGE_CACHING", "true").strip().lower()
    if value not in ("true", "false"):
        raise ValueError("SALAD_IMAGE_CACHING must be true or false")
    return value == "true"


'''


def patch_legacy(text: str) -> str:
    # Idempotent on already-patched source; rejects partially modified source.
    if 'def image_caching_enabled():' in text:
        for fragment in ('"image_caching": image_caching_enabled()',
                         'drift.append("container.image_caching")'):
            if fragment not in text:
                raise ValueError('salad-worker/deploy_salad.py: incomplete existing patch')
        return text
    text = exact_replace(text,
        'def validate_configuration():\n',
        caching_function() + 'def validate_configuration():\n',
        1, 'legacy helper')
    old = '"image": IMAGE,\n'
    if text.count(old) != 2:
        raise ValueError('legacy group image anchors changed')
    text = re.sub(r'(?m)^(\s*)"image": IMAGE,\n',
                  lambda m: m.group(0) + m.group(1) + '"image_caching": image_caching_enabled(),\n',
                  text)
    text = exact_replace(text,
        '    if container.get("image") != IMAGE:\n        drift.append("image")\n',
        '    if container.get("image") != IMAGE:\n        drift.append("image")\n'
        '    if container.get("image_caching") != image_caching_enabled():\n'
        '        drift.append("container.image_caching")\n',
        1, 'legacy cache drift')
    return text


def patch_backend(text: str) -> str:
    if 'def image_caching_enabled():' in text:
        for fragment in ('"image_caching": image_caching_enabled()',
                         '"image_caching": (group.get("container") or {}).get("image_caching")'):
            if fragment not in text:
                raise ValueError('backend/app/salad_control.py: incomplete existing patch')
        return text
    text = exact_replace(text,
        'def _new_group_payload(config, gpu_id):\n',
        caching_function() + 'def _new_group_payload(config, gpu_id):\n',
        1, 'backend helper')
    # Both direct and Salad Queue group creation paths.
    if text.count('"image": config["image"],\n') != 2:
        raise ValueError('backend group image anchors changed')
    text = re.sub(r'(?m)^(\s*)"image": config\["image"\],\n',
                  lambda m: m.group(0) + m.group(1) + '"image_caching": image_caching_enabled(),\n', text)
    text = exact_replace(text,
        '        "name": group.get("name") or configured_group,\n',
        '        "name": group.get("name") or configured_group,\n'
        '        "image_caching": (group.get("container") or {}).get("image_caching"),\n',
        1, 'sanitized status')
    # Existing idle groups: on an authorized changed draft deploy, also bring
    # the cache policy into line; do not mutate active groups.
    old = '''            if (old_group.get("container") or {}).get("image") != desired["image"]:
                _api("PATCH", _group_path(current["group_name"]),
                     payload={"container": {"image": desired["image"]}})
'''
    new = '''            existing_container = old_group.get("container") or {}
            if (existing_container.get("image") != desired["image"] or
                    existing_container.get("image_caching") != image_caching_enabled()):
                _api("PATCH", _group_path(current["group_name"]),
                     payload={"container": {"image": desired["image"],
                                            "image_caching": image_caching_enabled()}})
'''
    text = exact_replace(text, old, new, 1, 'idle group update')
    return text



def patch_instance_contract(text: str) -> str:
    if '"image_caching": data.get("image_caching")' in text:
        return text
    return exact_replace(text,
        '        "hold": data.get("hold"), "name": group_name, "group_name": group_name,\n',
        '        "hold": data.get("hold"), "name": group_name, "group_name": group_name,\n'
        '        "image_caching": data.get("image_caching"),\n',
        1, 'instance contract caching field')


def patch_env(text: str) -> str:
    if re.search(r'(?m)^SALAD_IMAGE_CACHING=', text):
        return text
    return exact_replace(text,
        'SALAD_GPU_NAME="RTX 5090 (32 GB)"\n',
        'SALAD_GPU_NAME="RTX 5090 (32 GB)"\n'
        '# OCI image caching for newly-created groups; existing groups need a safe update.\n'
        'SALAD_IMAGE_CACHING=true\n',
        1, 'env example')


def apply(repo: Path, *, check=False) -> dict[str, str]:
    transforms = {
        'salad-worker/deploy_salad.py': patch_legacy,
        'backend/app/salad_control.py': patch_backend,
        'backend/app/instance_contract.py': patch_instance_contract,
        '.env.example': patch_env,
    }
    # All-or-nothing validation BEFORE writing anything.
    changes = {}
    originals = {}
    for relative, transform in transforms.items():
        path = repo / relative
        if not path.is_file():
            raise ValueError(f'Missing source: {relative}')
        original = path.read_text(encoding='utf-8')
        revised = transform(original)
        if path.suffix == '.py':
            ast.parse(revised, filename=relative)
        originals[relative] = original
        if revised != original:
            changes[relative] = revised
    if check:
        return {relative: 'change-needed' if relative in changes else 'already-applied'
                for relative in transforms}
    for relative, revised in changes.items():
        (repo / relative).write_text(revised, encoding='utf-8')
    return {relative: 'updated' if relative in changes else 'already-applied'
            for relative in transforms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd(), help='comfyui-controller checkout')
    parser.add_argument('--check', action='store_true', help='Read-only validation, no writes')
    args = parser.parse_args()
    try:
        report = apply(args.repo.resolve(), check=args.check)
    except (OSError, ValueError, SyntaxError) as exc:
        print(f'PATCH REFUSED: {exc}', file=sys.stderr)
        return 2
    for path, outcome in report.items():
        print(f'{outcome}: {path}')
    print('No GitHub or Salad API changes were made.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
