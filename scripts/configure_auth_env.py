#!/usr/bin/env python3
"""Update only managed env flags, preserving unknown deployment settings and secrets.
Requires existing private .env; never creates a new one with fake provider keys.
"""
from pathlib import Path
import argparse
import os
import secrets
from urllib.parse import urlsplit

FLAGS = {
 'AUTH_ENABLED':'true',
 'AUTH_MFA_ENABLED':'false',
 'AUTH_REGISTRATION_MODE':'disabled',
 'OWNER_ISOLATION_ENABLED':'true',
 'ACCOUNT_UI_ENABLED':'true',
 'MEDIA_LIBRARY_ENABLED':'true',
 'MODEL_REGISTRY_ENABLED':'true',
 'DYNAMIC_PARAMETERS_ENABLED':'true',
 'WORKFLOW_COMPILER_ENABLED':'true',
 'WORKFLOW_STUDIO_ENABLED':'true',
 'WORKFLOW_STUDIO_POWER_USERS_ENABLED':'false',
 'SCHEDULER_V12_UI_ENABLED':'false',
 'VIDEO_V13_ENABLED':'false',
 'WORKER_V11_ENABLED':'false',
 'DIRECT_GPU_AUTO_CONTROL':'false',
}

def configure(path:Path, origin:str):
    origin=origin.rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RuntimeError('Public origin must be exactly https://your.domain (no path or credentials)')
    path=path.resolve()
    if not path.is_file():raise RuntimeError('Production private .env missing; refusing to continue')
    raw=path.read_text(encoding='utf-8')
    if '\r' in raw:raise RuntimeError('Unsupported CR line endings in .env')
    pairs={}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith('#') or '=' not in line:continue
        k,val=line.split('=',1)
        if k.strip() in pairs: raise RuntimeError('Duplicate .env key: '+k.strip())
        pairs[k.strip()]=val.strip().strip('"\'')
    if not pairs.get('APP_INTERNAL_TOKEN') or not pairs.get('DIRECT_WORKER_TOKEN'):
        raise RuntimeError('Existing admin/worker secrets are missing; refusing to deploy')
    if pairs.get('DB_PATH') != '/app/data/controller.db':
        raise RuntimeError('Only standard SQLite volume layout is supported; check DB_PATH')
    secret=pairs.get('AUTH_CSRF_SECRET','')
    if len(secret)<32: secret=secrets.token_urlsafe(48)
    updates={**FLAGS,'AUTH_CSRF_SECRET':secret,'AUTH_PUBLIC_ORIGIN':origin}
    rendered=[];found=set()
    for line in raw.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key=line.split('=',1)[0].strip()
            if key in updates:
                rendered.append(key+'='+updates[key]);found.add(key);continue
        rendered.append(line)
    for key,value in updates.items():
        if key not in found:rendered.append(key+'='+value)
    # In-place replacement with private permissions; source copy must be backed up by deployment script first.
    import tempfile
    fd,name=tempfile.mkstemp(prefix='.comfy-deploy-env-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as output:
            output.write('\n'.join(rendered)+'\n')
            output.flush();os.fsync(output.fileno())
        os.chmod(name,0o600)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    print('PRIVATE ENV updated. Auth enabled; public origin:',origin,'GPU auto-control disabled. Secrets not shown.')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('envfile',type=Path)
    ap.add_argument('--origin',default='https://comfy.imannasr.com')
    a=ap.parse_args()
    configure(a.envfile,a.origin)
