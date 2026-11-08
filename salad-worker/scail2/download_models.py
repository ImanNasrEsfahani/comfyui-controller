#!/usr/bin/env python3
"""Populate ComfyUI models from official HF repos. Verify known SHA-256s.
BAKE_MODE=thin => run once at Salad cold start (needs >=100GB disk).
BAKE_MODE=baked => GitHub large-runner downloads during image build.
"""
import hashlib
import json
import os
from pathlib import Path
def hf_hub_download(*args, **kwargs):
    """Load the optional Hugging Face downloader only for actual model IO.

    CI unit tests and offline tooling import this module without model-download
    dependencies. The SCAIL-2 Docker image installs huggingface_hub for runtime.
    Keeping this callable at module scope also supports deterministic mocking.
    """
    try:
        from huggingface_hub import hf_hub_download as _download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required for model downloads; "
            "install with: python -m pip install 'huggingface_hub>=0.35,<2'"
        ) from exc
    return _download(*args, **kwargs)

MODELS_ROOT=Path(os.environ.get('SCAIL2_MODELS_ROOT','/opt/ComfyUI/models'))
CATALOG=Path(__file__).with_name('models.json')


def hash_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while data:=f.read(8*1024*1024):h.update(data)
    return h.hexdigest()


def download():
    entries=json.loads(CATALOG.read_text())['artifacts']
    for entry in entries:
        destination=(MODELS_ROOT/entry['destination']).resolve()
        if not destination.is_relative_to(MODELS_ROOT.resolve()):raise ValueError('Invalid artifact path')
        destination.parent.mkdir(parents=True,exist_ok=True)
        expected=entry.get('sha256')
        if destination.is_file() and destination.stat().st_size>100_000:
            if expected and hash_file(destination)!=expected:
                destination.unlink()
            else:
                print('[model] cached:',entry['role'],flush=True);continue
        print('[model] fetching:',entry['role'],entry['repo'],entry['path'],flush=True)
        downloaded=Path(hf_hub_download(repo_id=entry['repo'],filename=entry['path'],
                                       revision=entry.get('revision','main'),token=os.getenv('HF_TOKEN') or None))
        if expected and hash_file(downloaded)!=expected:raise RuntimeError('Model digest mismatch: '+entry['role'])
        # Hardlink to HF cache (same filesystem) rather than duplicating 50+ GB.
        # If mounted on a different filesystem, use a read-only symlink.
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        try:
            os.link(downloaded,destination)
        except OSError:
            # The model directory may be on a separate Salad volume.
            # Copy rather than link to a cache that can disappear.
            import shutil
            shutil.copyfile(downloaded,destination)
        if expected and hash_file(destination)!=expected:
            destination.unlink(missing_ok=True)
            raise RuntimeError('Installed model digest mismatch: '+entry['role'])
    print('[model] all required artifacts verified/present',flush=True)

if __name__=='__main__':download()
