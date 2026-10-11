#!/usr/bin/env python3
"""Static router-mount audit + optional read-only FastAPI OpenAPI export.

Static presence of a file is NOT proof of a mounted or correctly authorized API.
"""
from __future__ import annotations
import argparse,ast,hashlib,importlib,json,os,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

REQUIRED_MODULES=('auth','owner_api','account_api','media_api','registry_api',
 'parameters_api','workflow_api','studio_api','worker_v11_api','scheduler_v12_api','video_api')

def static_inventory(repo:Path)->dict:
    main=repo/'backend/app/main.py'
    if not main.is_file():raise ValueError('Complete checkout with backend/app/main.py required')
    source=main.read_text(encoding='utf8')
    parsed=ast.parse(source)
    imports=set()
    for node in ast.walk(parsed):
        if isinstance(node,ast.ImportFrom):
            if node.module in REQUIRED_MODULES:imports.add(node.module)
            if node.module is None:
                imports.update(alias.name for alias in node.names if alias.name in REQUIRED_MODULES)
    # Imported aliases are not enough: ensure each router included in app.
    inclusion=set()
    for node in ast.walk(parsed):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='include_router':
            if node.args and isinstance(node.args[0],ast.Name):inclusion.add(node.args[0].id)
    modules={}
    for name in REQUIRED_MODULES:
        p=repo/'backend/app'/f'{name}.py'
        exists=p.is_file()
        module_imported=name in imports or bool(re.search(r'from\s+\.\s*'+re.escape(name)+r'\s+import\b',source))
        # Qualified names are recognized only if actually bound to an include_router call.
        alias_match=re.findall(r'from\s+\.'+re.escape(name)+r'\s+import\s+router\s+as\s+([A-Za-z_][\w]*)',source)
        mounted=any(alias in inclusion for alias in alias_match)
        modules[name]={'source_present':exists,'imported':module_imported,'router_mount_observed':mounted,
                       'status':'MOUNT_OBSERVED_ONLY' if mounted else 'BLOCKED_UNMOUNTED'}
    return {'at_utc':datetime.now(timezone.utc).isoformat(),
            'main_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'main_include_router_arguments':sorted(inclusion),'modules':modules,
            'readiness':'BLOCKED' if any(not v['router_mount_observed'] for v in modules.values()) else 'STATIC_ONLY',
            'warning':'Static matching does not establish authentication, route order, worker capability or live E2E'}

def runtime_inventory(repo:Path)->dict:
    sys.path.insert(0,str(repo/'backend'))
    app=importlib.import_module('app.main').app
    schema=app.openapi()  # No network/DB/provider requests.
    paths={p:sorted(method for method in operations if method.lower() in ('get','post','put','patch','delete')) for p,operations in schema.get('paths',{}).items()}
    normalized=json.dumps(schema,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return {'openapi_sha256':hashlib.sha256(normalized.encode()).hexdigest(),
            'route_count':sum(len(v) for v in paths.values()),'route_paths':paths,
            'runtime_readiness':'NOT VERIFIED — local imported object only'}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path('.'));p.add_argument('--output',type=Path)
    p.add_argument('--runtime',action='store_true');p.add_argument('--strict',action='store_true')
    a=p.parse_args(argv)
    try:
        result=static_inventory(a.repo)
        if a.runtime:result['runtime']=runtime_inventory(a.repo.resolve())
    except (ValueError,ImportError,AttributeError,RuntimeError,OSError,SyntaxError) as e:
        print('API INVENTORY FAILED:',type(e).__name__,str(e),file=sys.stderr);return 2
    data=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(data)
    else:print(data,end='')
    if a.strict and result['readiness']!='STATIC_ONLY':return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
