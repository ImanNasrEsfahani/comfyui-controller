#!/usr/bin/env python3
"""Verify Phase10 changed files copied into exact read-only-source Git checkout.

No rewriting, GitHub APIs, database writes or Git operations besides rev-parse.
Stage09 installation is still independently required (source-pinned installer).
"""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
BASE='d51a4eac487bee4f69808a9e8d49016fcafe624a'
BASE_BLOBS={
 'backend/app/workflow_api.py':'af1bb1fd8dac823098009290b4d10233d76b282a',
 'frontend/src/app/router.jsx':'551bd31b7a4c95b6519776241086de53bc32c17d',
 'frontend/src/auth/routeUtils.js':'21dd8d37e7cde7ddbe0fd376d057e68013220bfd',
}
FILES=[
 'backend/app/workflow_api.py','backend/app/studio_api.py','backend/app/migrations/phase10.py',
 'backend/workflows.env.phase10.example','frontend/src/app/router.jsx','frontend/src/auth/routeUtils.js',
 'frontend/src/pages/workflows/studioClient.js','frontend/src/pages/workflows/StudioV2.jsx',
 'frontend/src/pages/workflows/studio.css','frontend/src/components/workflow-canvas/graphEdit.mjs',
 'frontend/src/components/workflow-canvas/WorkflowCanvas.jsx',
]
def blob(data):return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
def verify(root,expected_sha,manifest):
 if not (root/'.git').is_dir():raise RuntimeError('Complete local Git checkout required')
 head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
 if head!=BASE:raise RuntimeError('Wrong HEAD, refuse stale checkout')
 for file,expected in BASE_BLOBS.items():
  content=subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{file}'])
  if blob(content)!=expected:raise RuntimeError('Base GitHub blob mismatch: '+file)
 for file in FILES:
  p=root/file
  if not p.is_file():raise RuntimeError('ZIP file missing: '+file)
  actual=hashlib.sha256(p.read_bytes()).hexdigest()
  if actual!=manifest[file]:raise RuntimeError('Changed file hash mismatch: '+file)
 print('PHASE10 COPY VERIFIED: exact pinned base, all changed files have expected sha256; NO deployment performed')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path('.'));p.add_argument('--manifest',type=Path,default=Path('PHASE10-PATCH-MANIFEST.json'));args=p.parse_args()
 try:
  import json
  m=json.loads(args.manifest.read_text(encoding='utf-8'))
  verify(args.repo.resolve(),BASE,{item['path']:item['sha256'] for item in m['files']})
 except (RuntimeError,OSError,ValueError,KeyError,subprocess.CalledProcessError) as e:print('REFUSED:',e,file=sys.stderr);sys.exit(2)
