#!/usr/bin/env python3
"""BuildKit-friendly model sharding (2 GiB per OCI layer) for baked mode.
Downloads are in a BuildKit cache, NOT copied into the image until sliced.
At Salad startup models are restored onto the ephemeral disk then SHA-verified.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from huggingface_hub import hf_hub_download

PART=2*1024*1024*1024
ROOT=Path('/opt/scail2/model-parts')
TARGET=Path(os.getenv('SCAIL2_MODELS_ROOT','/opt/ComfyUI/models'))
ENTRIES={x['role']:x for x in json.loads(Path(__file__).with_name('models.json').read_text())['artifacts']}


def slice_file(role,index):
    if role not in ENTRIES or not (0<=index<64):raise ValueError('Unknown model part')
    entry=ENTRIES[role]
    source=Path(hf_hub_download(repo_id=entry['repo'],filename=entry['path'],
                                revision=entry.get('revision','main'),token=os.getenv('HF_TOKEN') or None))
    offset=index*PART
    if offset>=source.stat().st_size:return
    folder=ROOT/role;folder.mkdir(parents=True,exist_ok=True)
    dest=folder/f'{index:03d}.part'
    if dest.exists():return
    with source.open('rb') as src,dest.open('wb') as dst:
        src.seek(offset)
        remaining=min(PART,source.stat().st_size-offset)
        while remaining:
            chunk=src.read(min(8*1024*1024,remaining))
            if not chunk:raise RuntimeError('Short model read')
            dst.write(chunk);remaining-=len(chunk)
    print(f'[parts] {role} #{index} {dest.stat().st_size} bytes')


def validate_parts():
    """Verify COMPLETE ordered model parts before publishing a baked image.

    Every artifact has a known upstream SHA256; missing tail pieces fail as
    incomplete digest, not silently pass during Docker Build.
    """
    for role, entry in ENTRIES.items():
        folder = ROOT / role
        parts = sorted(folder.glob('*.part'))
        if not parts or [p.name for p in parts] != [f'{i:03d}.part' for i in range(len(parts))]:
            raise RuntimeError('Missing/out-of-order baked model parts: '+role)
        expected = entry.get('sha256')
        if not expected:
            raise RuntimeError('Manifest lacks authoritative digest: '+role)
        h = hashlib.sha256()
        for index, part in enumerate(parts):
            if index != len(parts)-1 and part.stat().st_size != PART:
                raise RuntimeError('Short non-final model shard: '+role)
            if not 0 < part.stat().st_size <= PART:
                raise RuntimeError('Empty or oversized model shard: '+role)
            with part.open('rb') as inp:
                while block := inp.read(8*1024*1024):h.update(block)
        if h.hexdigest() != expected:
            raise RuntimeError('Baked model hash mismatch: '+role)
        print('[parts] checksum verified',role,flush=True)


def restore():
    validate_parts()
    for role,entry in ENTRIES.items():
        folder=ROOT/role
        parts=sorted(folder.glob('*.part'))
        if not parts or [f'{i:03d}.part' for i in range(len(parts))]!=[x.name for x in parts]:
            raise RuntimeError('Missing/out-of-order baked model parts: '+role)
        dest=TARGET/entry['destination'];dest.parent.mkdir(parents=True,exist_ok=True)
        h=hashlib.sha256();tmp=dest.with_suffix('.rebuilding')
        try:
            with tmp.open('wb') as out:
                for part in parts:
                    with part.open('rb') as inp:
                        while block:=inp.read(8*1024*1024):
                            h.update(block);out.write(block)
            if entry.get('sha256') and h.hexdigest()!=entry['sha256']:
                raise RuntimeError('Baked model digest mismatch: '+role)
            tmp.replace(dest)
        finally:tmp.unlink(missing_ok=True)
        print('[parts] restored',role,flush=True)

if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='slice':slice_file(sys.argv[2],int(sys.argv[3]))
    elif sys.argv[1:]==['restore']:restore()
    elif sys.argv[1:]==['verify']:validate_parts()
    else:sys.exit('usage: model_parts.py slice ROLE INDEX | restore')
