#!/usr/bin/env python3
"""Verify all files shipped in the audited SCAIL-2 overlay. Read-only."""
from hashlib import sha256
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'SHA256SUMS.txt'


def main():
    expected=[]
    for line in MANIFEST.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        digest,separator,relative=line.partition('  ')
        if separator!='  ' or len(digest)!=64 or '/' in digest:
            raise ValueError('Invalid SHA256 manifest entry')
        path=(ROOT/relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
            raise ValueError('Missing or unsafe package file: '+relative)
        actual=sha256(path.read_bytes()).hexdigest()
        if actual!=digest:raise ValueError('Integrity mismatch: '+relative)
        expected.append(relative)
    if len(expected)!=len(set(expected)) or not expected:
        raise ValueError('Empty or duplicate integrity manifest')
    print(f'Integrity OK: {len(expected)} files verified')


if __name__=='__main__':
    try:main()
    except Exception as exc:sys.exit('Overlay integrity FAIL: '+str(exc))
