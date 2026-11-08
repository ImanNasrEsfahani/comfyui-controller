#!/usr/bin/env python3
"""Fetch an immutable ComfyUI API template and verify its Git blob ID."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

UPSTREAM_COMMIT='91a79f518fc48ae4546fa815eacffa4bf194a3c6'
GIT_BLOB_SHA='5adc858efef8f9fe8d44e4166489d5b0553c2a87'
SOURCE=f'https://raw.githubusercontent.com/ruashots/scail2-skill/{UPSTREAM_COMMIT}/scripts/scail2_workflow.json'


def verify(raw):
    digest=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if digest != GIT_BLOB_SHA:
        raise ValueError(f'Pinned workflow checksum mismatch: {digest}')
    doc=json.loads(raw)
    if doc.get('114',{}).get('class_type')!='WanSCAILToVideo':
        raise ValueError('Expected SCAIL-2 model node missing')
    return doc


def main():
    with urlopen(SOURCE,timeout=60) as response:raw=response.read(100_000)
    verify(raw)
    target=Path(__file__).with_name('scail2_workflow.json')
    target.write_bytes(raw)
    print(f'Verified workflow downloaded: {target} ({len(raw)} bytes)')

if __name__=='__main__':main()
