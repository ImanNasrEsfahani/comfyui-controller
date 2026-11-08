#!/usr/bin/env python3
"""Install verified Hugging Face artifacts into ComfyUI without broken symlinks.

Hugging Face snapshot paths are often relative symlinks pointing into the HF
blob cache. Calling os.link(snapshot_symlink, model_path) on Linux can hardlink
the *symlink*, leaving a dangling link in ComfyUI's model directory. Resolve
the snapshot to its actual blob file before hardlinking, verify SHA-256, and
publish via an atomic rename. No large model files are stored in the git repo.

This is the thin-worker installer. The baked worker uses model_parts.py.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def hf_hub_download(*args, **kwargs):
    """Import only when needed; offline CI can import this module."""
    try:
        from huggingface_hub import hf_hub_download as download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required for model downloads; "
            "install with: python -m pip install 'huggingface_hub>=0.35,<2'"
        ) from exc
    return download(*args, **kwargs)


MODELS_ROOT = Path(os.environ.get('SCAIL2_MODELS_ROOT', '/opt/ComfyUI/models'))
CATALOG = Path(__file__).with_name('models.json')


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_destination(raw: str) -> Path:
    """Do not follow a pre-existing dangling file symlink outside models root."""
    if not isinstance(raw, str) or not raw:
        raise ValueError('Missing model destination')
    relative = Path(raw)
    if relative.is_absolute() or '..' in relative.parts or relative.name in ('', '.', '..'):
        raise ValueError('Unsafe model destination')
    root = MODELS_ROOT.resolve()
    parent = (root / relative.parent).resolve()
    if not parent.is_relative_to(root):
        raise ValueError('Model destination escapes model root')
    return parent / relative.name


def _install_atomic(source: Path, destination: Path, expected: str | None, role: str) -> None:
    """Install via hardlink to *real HF blob*, or copy across volumes.

    The destination is replaced only after the staging file passes verification;
    a failed download/install cannot leave a half-written model at the final
    path. A previous broken HF-snapshot symlink is safely replaced on success.
    """
    # Resolving the *source* is essential. HF snapshots are usually symlinks.
    blob = source.resolve(strict=True)
    if not blob.is_file():
        raise RuntimeError('Hugging Face artifact is not a regular file: ' + role)
    with tempfile.TemporaryDirectory(prefix='.scail2-install-', dir=str(destination.parent)) as staging_dir:
        staging = Path(staging_dir) / destination.name
        try:
            os.link(blob, staging)  # Actual blob inode, never the HF snapshot symlink.
            print('[model] linked verified blob:', role, flush=True)
        except OSError as exc:
            # Do not turn permissions / ENOSPC errors into an expensive giant copy.
            if exc.errno not in (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTSUP):
                raise
            required = blob.stat().st_size
            free = shutil.disk_usage(destination.parent).free
            if free < required + 256 * 1024 * 1024:
                raise RuntimeError('Insufficient storage for cross-filesystem model copy: ' + role) from exc
            print('[model] copying across filesystems:', role, flush=True)
            shutil.copyfile(blob, staging)
        if expected and hash_file(staging) != expected:
            raise RuntimeError('Installed model digest mismatch: ' + role)
        os.replace(staging, destination)


def download() -> None:
    entries = json.loads(CATALOG.read_text(encoding='utf-8'))['artifacts']
    for entry in entries:
        destination = _safe_destination(entry['destination'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = entry.get('sha256')
        role = entry['role']
        # Always heal legacy symlinks (valid or dangling) and tiny partial files.
        if (not destination.is_symlink() and destination.is_file()
                and destination.stat().st_size > 100_000
                and (not expected or hash_file(destination) == expected)):
            print('[model] cached:', role, flush=True)
            continue

        print('[model] fetching:', role, entry['repo'], entry['path'], flush=True)
        downloaded = Path(hf_hub_download(
            repo_id=entry['repo'],
            filename=entry['path'],
            revision=entry.get('revision', 'main'),
            token=os.getenv('HF_TOKEN') or None,
        ))
        # Validate upstream content BEFORE installing. For same-filesystem
        # hardlinks staging inode is also checked before atomic publication.
        actual = hash_file(downloaded)
        if expected and actual != expected:
            raise RuntimeError('Model digest mismatch: ' + role)
        _install_atomic(downloaded, destination, expected, role)
        print('[model] installed:', role, flush=True)
    print('[model] all required artifacts verified/present', flush=True)


if __name__ == '__main__':
    download()
