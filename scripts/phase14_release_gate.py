#!/usr/bin/env python3
"""Fail-closed, non-deploying release evidence inventory.

Never promotes historical reports into real-world verification. A passing unit
suite is one test fact, not a production release approval. Stdlib only.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = {
    0:'baseline',1:'database-identity',2:'authentication',3:'owner-isolation',
    4:'auth-ui-routing',5:'user-admin-dashboard',6:'private-gallery',
    7:'model-image-registry',8:'dynamic-params-lora-seed',9:'workflow-compiler',
    10:'workflow-studio',11:'worker-execution',12:'gpu-scheduling',
    13:'video-workflows',
}
REQUIRED_DOCUMENTS=('GLOBAL-RULES.txt','DECISIONS.md','LEGACY_OWNER_PLAN.md')
REQUIRED_EXTERNAL={
    'deployed_source_sha':'Running deployment SHA captured independently',
    'staging_restore':'Isolated copy of deployed database restored and checked',
    'owner_backfill':'Every legacy Job/Asset assigned to a verified owner',
    'two_account_http':'Two-account direct API authorization matrix in staging',
    'auth_browser':'Login, verification, session, MFA and CSRF browser evidence',
    'real_image_e2e':'Model -> Worker -> R2 -> Gallery -> Download -> Reuse',
    'real_worker_claim':'Signed Worker claim, lease, capability and output fencing',
    'provider_scale':'Provider-confirmed zero-to-ready-to-zero with finalization',
    'worker_digest':'OCI image provenance, approved model and node inventory',
    'cloudflare_r2':'Origin/edge TLS and private bucket authorization checks',
    'mobile_accessibility':'360px, RTL, keyboard and screen reader with screenshots',
    'rollback_rehearsal':'Realistic staged rollback and data compatibility proof',
}
OPEN_RE=re.compile(r'PARTIAL\s*/\s*BLOCKED|PARTIAL\s+\/\s+BLOCKED|NOT DONE_VERIFIED|not DONE_VERIFIED|still BLOCKED|BLOCKED|not a production-ready|safe offline proposal',re.I)

def git_sha(root:Path):
    try:
        return subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError,subprocess.CalledProcessError):
        return None

def source_status(text:str)->str:
    # Historical HANDOFFs are advisory; there is NO implicit release pass.
    return 'PARTIAL/BLOCKED' if OPEN_RE.search(text) else 'UNVERIFIED'

def inventory(root:Path, *, evidence:Path|None=None)->dict:
    root=root.resolve();phases=[]
    for n,name in PHASES.items():
        p=f'docs/phase-{n:02d}-{name}/HANDOFF.md';f=root/p
        if not f.is_file():
            phases.append({'phase':f'{n:02d}','status':'NOT RUN','source':p,'reason':'HANDOFF missing'})
            continue
        data=f.read_text(encoding='utf-8')
        phases.append({'phase':f'{n:02d}','status':source_status(data),'source':p,
                       'sha256':hashlib.sha256(data.encode()).hexdigest(),
                       'reason':'Historical handoff is not deployment evidence'})
    doc_checks={p:(root/p).is_file() for p in REQUIRED_DOCUMENTS}
    # An evidence file from a local machine may contain unverified claims. It is
    # deliberately NOT sufficient to authorize release, even if all are supplied.
    supplied=[]
    if evidence and evidence.is_dir():
        supplied=sorted(p.name for p in evidence.iterdir() if p.is_file() and p.suffix=='.json')[:100]
    return {
        'schema_version':1,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'source_sha':git_sha(root),'decision_files':doc_checks,
        'phases':phases,
        'external_gates':{k:{'status':'NOT RUN','required_evidence':v} for k,v in REQUIRED_EXTERNAL.items()},
        'submitted_evidence_files_unverified':supplied,
        'release_status':'BLOCKED',
        'reason':'No independent, environment-bound, operator-approved E2E/backup/runtime attestations; historical unit tests cannot certify release',
        'feature_policy':'Keep new multi-user Generation/Worker/Video/Scale flags OFF',
    }

def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path);p.add_argument('--evidence-dir',type=Path)
    p.add_argument('--enforce',action='store_true',help='Fail if release is not independently verified (currently always blocked)')
    a=p.parse_args(argv);result=inventory(a.repo,evidence=a.evidence_dir)
    rendered=json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(rendered,encoding='utf-8')
    else:print(rendered,end='')
    if a.enforce and result['release_status']!='DONE_VERIFIED':
        print('RELEASE REFUSED: independent approval and live evidence are mandatory',file=sys.stderr)
        return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
