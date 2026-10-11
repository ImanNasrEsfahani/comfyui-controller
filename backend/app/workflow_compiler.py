"""Phase09 strict, non-dispatching semantic DAG -> ComfyUI graph compiler.

Never accept arbitrary class_type, node code, shell, filesystem paths, R2 keys or URL.
This is a catalog of syntax-known mappings, NOT an attested Worker inventory.
The returned graph is for isolated preview/persistence only; no provider calls.
"""
from __future__ import annotations
import hashlib
import json
import re
from copy import deepcopy

MAX_NODES = 64
MAX_EDGES = 128
SAFE_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
SAFE_MODEL = re.compile(r'^[A-Za-z0-9_-]{1,96}$')
SECRET = re.compile(r'(?i)(secret|password|token|authorization|api[_-]?key|vault://|s3://|https?://|/opt/|\.\./|\\)')

class CompileError(ValueError):
    def __init__(self, code, path, message):
        super().__init__(message)
        self.code, self.path = code, path

def fail(code, path, detail):
    raise CompileError(code, path, detail)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

# Output map is ordered: ComfyUI links use zero-based indexes.
# False means the *semantic* draft is legal, but no executable Worker mapping is confirmed.
NODE_KINDS = {
 'checkpoint': ('CheckpointLoaderSimple', {}, {'model': 'model', 'clip': 'clip', 'vae': 'vae'}, False),
 'prompt': ('CLIPTextEncode', {'clip': 'clip', 'text': 'text'}, {'conditioning': 'conditioning'}, True),
 'latent': ('EmptyLatentImage', {'width':'integer','height':'integer','batch_size':'integer'}, {'latent':'latent'}, True),
 'sampler': ('KSampler', {'model':'model','positive':'conditioning','negative':'conditioning','latent_image':'latent', 'seed':'integer','steps':'integer','cfg':'number','sampler_name':'text','scheduler':'text','denoise':'number'}, {'latent':'latent'}, True),
 'decode': ('VAEDecode', {'samples':'latent','vae':'vae'}, {'image':'image'}, True),
 'image_input': ('LoadImage', {'image':'image'}, {'image':'image'}, False),
 'encode': ('VAEEncode', {'pixels':'image','vae':'vae'}, {'latent':'latent'}, True),
 'image_output': ('SaveImage', {'images':'image','filename_prefix':'text'}, {}, True),
 'multi_reference': ('UNVERIFIED_MULTI_REFERENCE', {'identity':'image','clothing_pose':'image','instruction':'text'}, {'conditioning':'conditioning'}, False),
 'video_generation': ('UNVERIFIED_IMAGE_TO_VIDEO', {'start_frame':'image','prompt':'text','seconds':'integer','fps':'integer'}, {'frames':'frames'}, False),
 'video_output': ('UNVERIFIED_VIDEO_OUTPUT', {'frames':'frames'}, {}, False),
}
# Static values are fixed by backend, never set by a user-supplied graph.
FIXED = {'sampler': {'sampler_name':'euler','scheduler':'normal','denoise':1.0},
         'image_output': {'filename_prefix':'controller'}, 'latent': {'batch_size':1}}

VALID_INTENTS={'text2img','img2img','multi_ref','inpaint','upscale','text2video','image2video'}
PORT_TYPES={'text','integer','number','image','mask','video','model','clip','vae','conditioning','latent','frames'}

def validated(spec):
    if not isinstance(spec, dict) or set(spec) != {'intent','nodes','edges','inputs','outputs'}:
        fail('invalid_graph','graph','Exactly intent,nodes,edges,inputs,outputs required')
    if not isinstance(spec['intent'],str) or spec['intent'] not in VALID_INTENTS:fail('invalid_intent','intent','Unsupported intent')
    nodes,edges,inputs,outputs=(spec[x] for x in ('nodes','edges','inputs','outputs'))
    if not isinstance(nodes,list) or not 1<=len(nodes)<=MAX_NODES:fail('graph_size','nodes','Invalid node count')
    if not isinstance(edges,list) or len(edges)>MAX_EDGES:fail('graph_size','edges','Too many edges')
    if not isinstance(inputs,list) or len(inputs)>64 or not isinstance(outputs,list) or not 1<=len(outputs)<=16:
        fail('graph_size','inputs','Too many inputs or missing outputs')
    node_by_id={}
    for i,item in enumerate(nodes):
        if not isinstance(item,dict) or set(item)!={'id','kind'}:fail('invalid_node',f'nodes.{i}','Nodes accept only id/kind; no executable code or custom class')
        nid=item['id'];kind=item['kind']
        if not isinstance(nid,str) or not SAFE_ID.fullmatch(nid) or nid in node_by_id:fail('invalid_node',f'nodes.{i}.id','Bad or duplicate node')
        if not isinstance(kind,str) or kind not in NODE_KINDS:fail('unknown_node',f'nodes.{i}.kind','Node is not on audited semantic allowlist')
        node_by_id[nid]=kind
    wired=set();adj={nid:set() for nid in node_by_id};indeg={nid:0 for nid in node_by_id}
    for i,e in enumerate(edges):
        p=f'edges.{i}'
        if not isinstance(e,dict) or set(e)!={'from','out','to','in'}:fail('invalid_edge',p,'Required from,out,to,in')
        src,dst=e['from'],e['to']
        if not isinstance(src,str) or not isinstance(dst,str) or src not in node_by_id or dst not in node_by_id:fail('invalid_edge',p,'Unknown node ID')
        out=NODE_KINDS[node_by_id[src]][2];inp=NODE_KINDS[node_by_id[dst]][1]
        if not isinstance(e['out'],str) or not isinstance(e['in'],str) or e['out'] not in out or e['in'] not in inp:fail('invalid_port',p,'Unknown named source/destination port')
        left,right=out[e['out']],inp[e['in']]
        if left!=right and not (left=='integer' and right=='number'):
            fail('port_type',p,'Ports are not type-compatible')
        target=(dst,e['in'])
        if target in wired:fail('duplicate_binding',p,'One input port cannot have two sources')
        wired.add(target)
        if dst not in adj[src]:adj[src].add(dst);indeg[dst]+=1
    keys=set();input_by_key={}
    for i,inp in enumerate(inputs):
        p=f'inputs.{i}'
        if not isinstance(inp,dict) or set(inp)!={'key','type','role','node','port','required'}:fail('invalid_input',p,'Input schema fields missing/extra')
        key=inp['key']
        if not isinstance(key,str) or not SAFE_ID.fullmatch(key) or key in keys:fail('invalid_input',p,'Duplicate/invalid input key')
        keys.add(key);input_by_key[key]=inp
        if not isinstance(inp['node'],str) or inp['node'] not in node_by_id:fail('invalid_input',p,'Input binding references unknown node')
        ports=NODE_KINDS[node_by_id[inp['node']]][1]
        if not isinstance(inp['port'],str) or not isinstance(inp['type'],str) or inp['port'] not in ports or ports[inp['port']]!=inp['type'] and not (inp['type']=='integer' and ports[inp['port']]=='number'):
            fail('input_type',p,'Binding is not supported by target node port')
        if inp['type'] not in PORT_TYPES or not isinstance(inp['required'],bool):fail('invalid_input',p,'Invalid input type/required')
        if not isinstance(inp['role'],str) or not SAFE_ID.fullmatch(inp['role']):fail('invalid_input',p,'Invalid role')
        target=(inp['node'],inp['port'])
        if target in wired:fail('duplicate_binding',p,'Target port already bound')
        wired.add(target)
    for node,kind in node_by_id.items():
        for port in NODE_KINDS[kind][1]:
            if (node,port) not in wired and port not in FIXED.get(kind,{}) and not (spec['intent']=='text2video' and kind=='video_generation' and port=='start_frame'):
                fail('missing_port',f'nodes.{node}.{port}','Required typed node port has no value')
    for i,out in enumerate(outputs):
        if not isinstance(out,dict) or set(out)!={'node','media_type'} or not isinstance(out['node'],str) or out['node'] not in node_by_id:
            fail('invalid_output',f'outputs.{i}','Invalid output node')
        expected='video' if node_by_id[out['node']]=='video_output' else 'image' if node_by_id[out['node']]=='image_output' else None
        if not expected or out['media_type']!=expected:fail('output_type',f'outputs.{i}','Output node/media mismatch')
    kinds=set(node_by_id.values())
    expected={
     'text2img':{'checkpoint','prompt','latent','sampler','decode','image_output'},
     'img2img':{'checkpoint','prompt','image_input','encode','sampler','decode','image_output'},
     'multi_ref':{'checkpoint','prompt','image_input','encode','multi_reference','sampler','decode','image_output'},
     'image2video':{'image_input','video_generation','video_output'},
     'text2video':{'video_generation','video_output'},
    }
    if spec['intent'] not in expected:
        fail('intent_unavailable','intent','Intent requires unavailable audited compiler bindings')
    if not expected[spec['intent']].issubset(kinds):
        fail('intent_graph_mismatch','intent','Required semantic blocks for selected intent are missing')
    def role_edge(role,target_kind,target_port):
        matches=[i for i in inputs if i['role']==role and i['type']=='image' and node_by_id[i['node']]=='image_input']
        targets=[n for n,k in node_by_id.items() if k==target_kind]
        return len(matches)==1 and len(targets)==1 and any(e['from']==matches[0]['node'] and e['out']=='image'
                 and e['to']==targets[0] and e['in']==target_port for e in edges)
    if spec['intent']=='img2img' and not role_edge('source','encode','pixels'):
        fail('role_binding','inputs','The authorized source Asset must feed VAEEncode.pixels')
    if spec['intent']=='multi_ref' and not (role_edge('identity','multi_reference','identity')
                                            and role_edge('clothing_pose','multi_reference','clothing_pose')):
        fail('role_binding','inputs','Identity and clothing/pose Asset slots must connect to fixed distinct ports')
    if spec['intent']=='image2video' and not role_edge('start_frame','video_generation','start_frame'):
        fail('role_binding','inputs','Start frame must bind to verified semantic frame input port')
    if spec['intent']=='text2video' and any(n['kind']=='image_input' for n in nodes):
        fail('intent_graph_mismatch','intent','Text-to-video draft cannot silently require an image')
    # Kahn's algorithm; a hidden cycle must not reach the compiler.
    frontier=sorted(n for n,v in indeg.items() if v==0);count=0
    while frontier:
        n=frontier.pop(0);count+=1
        for m in sorted(adj[n]):
            indeg[m]-=1
            if indeg[m]==0:frontier.append(m);frontier.sort()
    if count!=len(node_by_id):fail('graph_cycle','edges','Cycle detected in semantic workflow')
    if len(canonical(spec))>64000:fail('graph_size','graph','Graph exceeds 64 KiB')
    return deepcopy(spec)

def input_values(spec, supplied, authorize_asset=None):
    if not isinstance(supplied,dict):fail('invalid_parameters','parameters','Expected key-value object')
    expected={i['key']:i for i in spec['inputs']}
    for key in supplied:
        if key not in expected:fail('unsupported_parameter','parameters.'+key,'Input is not in selected Workflow version')
    safe={}
    for key,meta in expected.items():
        p='parameters.'+key
        if key not in supplied:
            if meta['required']:fail('missing_parameter',p,'Required value not supplied')
            continue
        value=supplied[key];kind=meta['type']
        if kind in ('text','image'):
            if not isinstance(value,str) or (kind=='text' and len(value)>10000) or (kind=='image' and not SAFE_MODEL.fullmatch(value)):
                fail('invalid_parameter',p,'Invalid text/opaque asset id')
            if kind=='image':
                if authorize_asset is None:fail('asset_authorization',p,'Asset ownership callback required')
                if not authorize_asset(value):fail('asset_access_denied',p,'Asset not owned or unavailable')
            elif SECRET.search(value):fail('unsafe_value',p,'Text with embedded URL/path/credential-like string is not supported in compiler preview')
        elif kind=='integer':
            # uint64 seed MUST be passed as decimal string; no JSON float precision.
            if key.lower()=='seed':
                if not isinstance(value,str) or not re.fullmatch(r'0|[1-9][0-9]{0,19}',value) or int(value)>2**64-1:fail('invalid_seed',p,'Invalid uint64 seed string')
                value=int(value)
            elif isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=100000:
                fail('invalid_parameter',p,'Invalid integer')
        elif kind=='number':
            import math
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=50:
                fail('invalid_parameter',p,'Finite bounded number required')
        else:fail('unbound_parameter',p,'No safe user value mapping for type')
        if key in ('width','height') and (not isinstance(value,int) or not 64<=value<=4096):
            fail('invalid_dimensions',p,'Dimensions outside safety bounds (not proof of model support)')
        if key in ('seconds','fps') and (not isinstance(value,int) or not 1<=value<=120):
            fail('invalid_duration',p,'Video duration or framerate outside absolute safety bounds')
        safe[key]=value
    return safe

def compile_graph(spec, supplied, *, authorize_asset=None, model_id=None):
    spec=validated(spec)
    resolved=input_values(spec,supplied,authorize_asset)
    if not model_id or not isinstance(model_id,str) or not SAFE_MODEL.fullmatch(model_id):
        fail('missing_model','model_version_id','Model must be a known version from server registry')
    nodes={n['id']:n['kind'] for n in spec['nodes']}
    bindings={(i['node'],i['port']):resolved[i['key']] for i in spec['inputs'] if i['key'] in resolved}
    graph={};not_dispatchable=[]
    for nid,kind in nodes.items():
        cls,ports,outputs,known=NODE_KINDS[kind]
        if not known:not_dispatchable.append(nid)
        actual=dict(FIXED.get(kind,{}))
        for port in ports:
            if (nid,port) in bindings:actual[port]=bindings[nid,port]
        graph[nid]={'class_type':cls,'inputs':actual}
    for e in spec['edges']:
        src=e['from'];dst=e['to'];index=list(NODE_KINDS[nodes[src]][2]).index(e['out'])
        graph[dst]['inputs'][e['in']]=[src,index]
    result={'contract_version':3,'workflow_spec_hash':sha(spec),'model_version_id':model_id,
            'graph':graph,'graph_hash':sha(graph),'runtime_verified':False,
            'dispatch_allowed':False,'unverified_nodes':not_dispatchable}
    return result

def preview(result):
    # Never give users compiled input data, prompts, private assets or runtime filenames.
    return {'graph_hash':result['graph_hash'],'workflow_spec_hash':result['workflow_spec_hash'],
            'node_count':len(result['graph']), 'node_types':sorted({n['class_type'] for n in result['graph'].values()}),
            'runtime_verified':False,'dispatch_allowed':False,
            'unverified_node_count':len(result['unverified_nodes'])}
