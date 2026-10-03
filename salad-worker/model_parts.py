#!/usr/bin/env python3
"""Store Qwen model assets as bounded OCI layers, then restore locally at startup.

Each Docker RUN calls `download` for exactly one part. Downloads MUST support HTTP
206 ranged responses; a server returning HTTP 200 for a range is rejected to
avoid accidentally baking the whole model into one Docker layer.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CHUNK_BYTES = 3_000_000_000  # <= 3.0 GB per model layer (before compression)
PARTS_ROOT = Path('/opt/qvr-salad/model-parts')
TARGET_ROOT = Path('/opt/ComfyUI/models')
SPECS = {
    'fp8': {
        'url': 'https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors',
        'sha256': 'c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e',
        'relative_target': 'diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors',
        'slots': 9,  # up to 27 GB; unused trailing slots are empty markers
    },
    'encoder': {
        'url': 'https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors',
        'sha256': 'cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4',
        'relative_target': 'text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors',
        'slots': 4,  # up to 12 GB
    },
}
CR_RE = re.compile(r'^bytes (\d+)-(\d+)/(\d+)$')


def ranged_response(url, first, last):
    req = Request(url, headers={
        'Range': f'bytes={first}-{last}',
        'Accept-Encoding': 'identity',
        'User-Agent': 'comfyui-controller-model-parts/1.0',
    })
    res = urlopen(req, timeout=180)
    if res.status != 206:
        res.close()
        raise ValueError('Model origin did not honor HTTP Range (expected 206). Refusing full-model download into one layer.')
    cr = res.headers.get('Content-Range', '')
    match = CR_RE.fullmatch(cr)
    if not match or (int(match[1]), int(match[2])) != (first, last):
        res.close()
        raise ValueError(f'Incorrect Content-Range: {cr!r}; expected {first}-{last}')
    return res, int(match[3])


def probe_size(url):
    for attempt in range(1, 5):
        try:
            res, total = ranged_response(url, 0, 0)
            with res:
                if len(res.read(2)) != 1:
                    raise OSError('Incomplete size probe')
                return total
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 4:
                raise
            print(f'Metadata request retry {attempt}/4: {exc}', flush=True)
            time.sleep(attempt * 3)


def download_chunk(kind, index, parts_root=PARTS_ROOT, chunk_bytes=CHUNK_BYTES, specs=SPECS):
    spec = specs[kind]
    if not 0 <= index < spec['slots']:
        raise ValueError(f'{kind}: chunk index {index} outside configured slots')
    total = probe_size(spec['url'])
    if total > spec['slots'] * chunk_bytes:
        raise ValueError(f'{kind}: {total} bytes exceed {spec["slots"]} * {chunk_bytes} bytes; increase slots')
    start = index * chunk_bytes
    destination = Path(parts_root) / kind / f'part-{index:02d}'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if start >= total:
        destination.write_bytes(b'')
        print(f'{kind} part-{index:02d}: no data (unused trailing slot)', flush=True)
        return destination
    end = min(start + chunk_bytes, total) - 1
    expected = end - start + 1
    for attempt in range(1, 5):
        partial = destination.with_suffix('.partial')
        partial.unlink(missing_ok=True)
        try:
            res, remote_total = ranged_response(spec['url'], start, end)
            if remote_total != total:
                res.close()
                raise OSError(f'Model size changed during download: {total} -> {remote_total}')
            with res:
                with partial.open('wb') as out:
                    shutil.copyfileobj(res, out, length=1024 * 1024)
                # copyfileobj returns None; check actual file length.
                actual = partial.stat().st_size
                if actual != expected:
                    raise OSError(f'Incomplete range: {actual} bytes, expected {expected}')
            os.replace(partial, destination)
            print(f'{kind} part-{index:02d}: {actual / 1e9:.3f} GB ({start}-{end}/{total})', flush=True)
            return destination
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            if isinstance(exc, HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 4:
                raise
            print(f'{kind} part-{index:02d}: retry {attempt}/4: {exc}', flush=True)
            time.sleep(attempt * 3)
    raise RuntimeError('unreachable')


def parts(kind, parts_root=PARTS_ROOT, chunk_bytes=CHUNK_BYTES, specs=SPECS):
    spec = specs[kind]
    result = []
    empty_seen = False
    for i in range(spec['slots']):
        part = Path(parts_root) / kind / f'part-{i:02d}'
        if not part.is_file():
            raise FileNotFoundError(f'Missing model part: {part}')
        size = part.stat().st_size
        if size > chunk_bytes:
            raise ValueError(f'Oversized model part: {part}')
        if size == 0:
            empty_seen = True
        elif empty_seen:
            raise ValueError(f'Nonempty chunk after empty marker: {part}')
        if size:
            result.append(part)
    if not result:
        raise ValueError(f'No model data for {kind}')
    return result


def digest_of_parts(kind, parts_root=PARTS_ROOT, chunk_bytes=CHUNK_BYTES, specs=SPECS):
    digest = hashlib.sha256()
    total = 0
    for part in parts(kind, parts_root, chunk_bytes, specs):
        with part.open('rb') as source:
            while True:
                buf = source.read(4 * 1024 * 1024)
                if not buf:
                    break
                digest.update(buf)
                total += len(buf)
    return digest.hexdigest(), total


def verify(kind, parts_root=PARTS_ROOT, chunk_bytes=CHUNK_BYTES, specs=SPECS):
    got, size = digest_of_parts(kind, parts_root, chunk_bytes, specs)
    expected = specs[kind]['sha256']
    if got != expected:
        raise ValueError(f'{kind} SHA256 mismatch: expected {expected}, got {got}')
    print(f'{kind}: verified {size / 1e9:.3f} GB across {len(parts(kind, parts_root, chunk_bytes, specs))} data parts', flush=True)
    return size


def restore(kind, parts_root=PARTS_ROOT, target_root=TARGET_ROOT, chunk_bytes=CHUNK_BYTES, specs=SPECS):
    spec = specs[kind]
    target = Path(target_root) / spec['relative_target']
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        h = hashlib.sha256()
        with target.open('rb') as source:
            for buf in iter(lambda: source.read(4 * 1024 * 1024), b''):
                h.update(buf)
        if h.hexdigest() == spec['sha256']:
            print(f'{kind}: already restored and verified', flush=True)
            return target
        raise ValueError(f'Existing model is invalid: {target}')
    chunks = parts(kind, parts_root, chunk_bytes, specs)
    bytes_needed = sum(p.stat().st_size for p in chunks)
    free = shutil.disk_usage(target.parent).free
    reserve = 1 * 1024**3
    if free < bytes_needed + reserve:
        raise OSError(f'Insufficient free disk to restore {kind}: need {bytes_needed + reserve} bytes, available {free}')
    print(f'{kind}: reconstructing {bytes_needed / 1e9:.2f} GB locally...', flush=True)
    partial = target.with_name(target.name + '.partial')
    partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    try:
        with partial.open('wb') as out:
            for chunk in chunks:
                with chunk.open('rb') as source:
                    while True:
                        buf = source.read(4 * 1024 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        digest.update(buf)
        if digest.hexdigest() != spec['sha256']:
            raise ValueError(f'{kind}: restored SHA256 mismatch; refusing to launch ComfyUI')
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    print(f'{kind}: model restored and SHA256 verified: {target}', flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    dl = commands.add_parser('download', help='Download ONE model range for ONE Docker layer')
    dl.add_argument('kind', choices=SPECS)
    dl.add_argument('index', type=int)
    vr = commands.add_parser('verify', help='SHA256-verify model parts without assembling a file')
    vr.add_argument('kind', choices=SPECS)
    commands.add_parser('restore', help='Reassemble and verify required models on container startup')
    args = parser.parse_args()
    if args.command == 'download':
        download_chunk(args.kind, args.index)
    elif args.command == 'verify':
        verify(args.kind)
    else:
        for kind in ('fp8', 'encoder'):
            restore(kind)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[model-parts] ERROR: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
