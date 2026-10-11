"""Backend-first Phase08 validation/seed/LoRA compiler helpers.

This module does NOT create Jobs, start Workers, or claim runtime compatibility.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal,InvalidOperation
import hashlib,json,re,secrets,math

MAX_SEED=(1<<64)-1
FIELD_TYPES={'string','text','integer','number','enum','boolean','image','multiselect','seed'}
IDENT=re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{0,79}$')
HEX=re.compile(r'^[a-f0-9]{64}$')
FORBIDDEN=re.compile(r'(secret|password|bearer|authorization|api[_-]?key|worker[_-]?token|vault://|s3://|https?://|signed[_-]?url)',re.I)

class ParameterError(ValueError):
 def __init__(self,code:str,path:str,message:str):
  super().__init__(message);self.code=code;self.path=path

def fail(path,msg,code='invalid_parameter'):raise ParameterError(code,path,msg)
def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def checksum(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def forbid(value,path='parameters',*,scan_values=False):
 if isinstance(value,dict):
  for k,v in value.items():
   if FORBIDDEN.search(str(k)):fail(path+'.'+str(k),'Sensitive field is not permitted','sensitive_field')
   forbid(v,path+'.'+str(k),scan_values=scan_values)
 elif isinstance(value,list):
  for idx,v in enumerate(value):forbid(v,f'{path}.{idx}',scan_values=scan_values)
 elif isinstance(value,str) and scan_values and FORBIDDEN.search(value):
  fail(path,'URLs, storage locations and credentials are not allowed','sensitive_value')

def validate_schema(data):
 if not isinstance(data,dict) or not {'schema_version','fields'}<=set(data) or set(data)-{'schema_version','fields','lora_slots'}:fail('schema','Invalid schema keys')
 if not isinstance(data['schema_version'],str) or not 1<=len(data['schema_version'])<=40:fail('schema_version','Invalid version')
 slots=data.get('lora_slots',{})
 if not isinstance(slots,dict) or len(slots)>16 or any(not isinstance(k,str) or not re.fullmatch(r'[a-f0-9-]{36}',k) or not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',v) for k,v in slots.items()) or len(set(slots.values()))!=len(slots):fail('lora_slots','Invalid LoRA node bindings')
 fields=data['fields']
 if not isinstance(fields,list) or not 1<=len(fields)<=80:fail('fields','Expected 1-80 fields')
 seen=set();safe=[]
 for index,f in enumerate(fields):
  path=f'fields.{index}'
  if not isinstance(f,dict) or not {'key','type'}<=set(f):fail(path,'Missing key/type')
  if set(f)-{'key','type','label','help','required','default','min','max','step','options','variable_key','supports_random','group'}:fail(path,'Unsupported schema metadata')
  key=f['key'];kind=f['type']
  if not isinstance(key,str) or not IDENT.fullmatch(key) or key in seen:fail(path+'.key','Invalid or duplicate field')
  seen.add(key)
  if kind not in FIELD_TYPES:fail(path+'.type','Invalid field type')
  if 'variable_key' in f and (not isinstance(f['variable_key'],str) or not IDENT.fullmatch(f['variable_key'])):fail(path+'.variable_key','Invalid binding')
  for x in ('label','help','group'):
   if x in f and (not isinstance(f[x],str) or len(f[x])>300):fail(path+'.'+x,'Invalid description')
  for x in ('required','supports_random'):
   if x in f and not isinstance(f[x],bool):fail(path+'.'+x,'Expected boolean')
  if kind in {'integer','number','seed'}:
   for x in ('min','max','step'):
    if x in f and (isinstance(f[x],bool) or not isinstance(f[x],(int,float)) or not math.isfinite(f[x])):fail(path+'.'+x,'Invalid numeric bound')
   if 'step' in f and f['step']<=0:fail(path+'.step','Step must be positive')
   if 'min' in f and 'max' in f and f['min']>f['max']:fail(path,'Reversed bounds')
  elif any(x in f for x in ('min','max','step')):fail(path,'Numeric bounds not valid for type')
  if kind in {'enum','multiselect'}:
   options=f.get('options')
   if not isinstance(options,list) or not 1<=len(options)<=100 or any(not isinstance(x,str) or len(x)>100 for x in options) or len(options)!=len(set(options)):fail(path+'.options','Invalid choices')
  elif 'options' in f:fail(path+'.options','Choices not supported')
  if kind=='seed' and any(x in f and (not isinstance(f[x],int) or isinstance(f[x],bool) or f[x]<0 or f[x]>MAX_SEED) for x in ('min','max','step')):fail(path,'Seed bounds must be uint64 integers')
  if kind=='seed' and ('supports_random' in f and not f['supports_random']):fail(path+'.supports_random','Seed policy requires explicit modes')
  safe.append(f)
 for f in safe:
  if 'default' in f:validate_value(f,f['default'],'fields.'+f['key']+'.default')
 forbid(data,'schema',scan_values=True)
 return {'schema_version':data['schema_version'],'fields':safe,'lora_slots':slots}

def seed_number(s,path='seed'):
 if isinstance(s,bool) or not isinstance(s,str) or not re.fullmatch(r'0|[1-9][0-9]{0,19}',s):fail(path,'Seed must be a decimal string','invalid_seed')
 n=int(s)
 if n>MAX_SEED:fail(path,'Seed outside uint64 domain','invalid_seed')
 return n

def validate_value(f,v,path):
 kind=f['type']
 if kind=='seed':
  number=seed_number(v,path)
  if number<int(f.get('min',0)) or number>int(f.get('max',MAX_SEED)):fail(path,'Seed outside model range','invalid_seed')
  if (number-int(f.get('min',0)))%int(f.get('step',1))!=0:fail(path,'Seed does not match model step','invalid_seed')
  return v
 if kind in ('string','text'):
  if not isinstance(v,str) or len(v)>10000:fail(path,'Expected text')
  return v
 if kind=='image':
  if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',v):fail(path,'Only opaque Asset IDs permitted, never URLs')
  return v
 if kind=='boolean':
  if not isinstance(v,bool):fail(path,'Expected boolean')
  return v
 if kind=='enum':
  if not isinstance(v,str) or v not in f['options']:fail(path,'Unsupported option')
  return v
 if kind=='multiselect':
  if not isinstance(v,list) or len(v)>30 or len(v)!=len(set(x for x in v if isinstance(x,str))) or any(not isinstance(x,str) or x not in f['options'] for x in v):fail(path,'Unsupported selection')
  return v
 if kind in ('integer','number'):
  if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or kind=='integer' and not isinstance(v,int):fail(path,'Expected finite '+kind)
  if kind=='integer' and abs(v)>((1<<53)-1):fail(path,'Large integer must use seed string if supported')
  if 'min' in f and v<f['min'] or 'max' in f and v>f['max']:fail(path,'Value out of range')
  if 'step' in f:
   try:
    base=Decimal(str(f.get('min',0)));q=(Decimal(str(v))-base)/Decimal(str(f['step']))
    if q!=q.to_integral_value():fail(path,'Value does not match step')
   except InvalidOperation:fail(path,'Invalid numeric step')
  return v
 fail(path,'Invalid value type')

def resolve(schema,provided,*,seed_mode='fixed',batch_count=1,batch_mode='SAME',rng=None):
 schema=validate_schema(schema)
 if not isinstance(provided,dict) or len(canonical(provided))>65536:fail('parameters','Expected parameter object <=64KiB')
 forbid(provided,'parameters',scan_values=False)
 bykey={f['key']:f for f in schema['fields']};unknown=set(provided)-set(bykey)
 if unknown:fail('parameters.'+sorted(unknown)[0],'Model does not support this parameter','unsupported_parameter')
 if not isinstance(batch_count,int) or isinstance(batch_count,bool) or not 1<=batch_count<=8:fail('batch_count','Invalid output count')
 if batch_mode not in ('SAME','INCREMENT','INDEPENDENT_RANDOM'):fail('batch_mode','Invalid batch mode')
 if seed_mode not in ('fixed','random','increment','variation'):fail('seed_mode','Unsupported seed mode')
 result={};sources={}
 for key,f in bykey.items():
  if key in provided:val=provided[key];sources[key]='user'
  elif 'default' in f:val=f['default'];sources[key]='schema'
  elif f.get('required') and f['type']!='seed':fail('parameters.'+key,'Required parameter missing','missing_parameter')
  else:continue
  if f['type']!='seed':result[key]=validate_value(f,val,'parameters.'+key)
  else:result[key]=val
 seed_fields=[f for f in bykey.values() if f['type']=='seed']
 if seed_mode!='fixed' and not seed_fields:fail('seed_mode','Selected model has no seed control')
 if len(seed_fields)>1:fail('schema.fields','Multiple seed fields unsupported')
 if seed_fields:
  key=seed_fields[0]['key']
  if seed_mode=='fixed':
   if key not in result:fail('parameters.'+key,'Fixed seed is required','missing_seed')
   first=seed_number(result[key],f'parameters.{key}')
  else:
   if not seed_fields[0].get('supports_random'):fail('seed_mode','Random seed not supported by this model')
   lo=int(seed_fields[0].get('min',0));hi=int(seed_fields[0].get('max',MAX_SEED));step=int(seed_fields[0].get('step',1))
   first=(rng or (lambda:lo+step*secrets.randbelow((hi-lo)//step+1)))()
   if not isinstance(first,int) or isinstance(first,bool) or first<lo or first>hi or (first-lo)%step:fail('seed','Invalid RNG result')
   result[key]=str(first);sources[key]='server_random'
  if batch_mode=='SAME':seeds=[str(first)]*batch_count
  elif batch_mode=='INCREMENT':
   if int(seed_fields[0].get('step',1))!=1:fail('batch_mode','Increment not supported by this model seed step')
   if first+batch_count-1>int(seed_fields[0].get('max',MAX_SEED)):fail('batch_mode','Seed overflow')
   seeds=[str(first+i) for i in range(batch_count)]
  else:
   if not seed_fields[0].get('supports_random'):fail('batch_mode','Independent random seeds not supported')
   lo=int(seed_fields[0].get('min',0));hi=int(seed_fields[0].get('max',MAX_SEED));step=int(seed_fields[0].get('step',1))
   seeds=[str(first)]+[str((rng or (lambda:lo+step*secrets.randbelow((hi-lo)//step+1)))()) for _ in range(batch_count-1)]
 else:seeds=[]
 return {'requested':deepcopy(provided),'effective':result,'sources':sources,'seeds_per_output':seeds,'schema_hash':checksum(schema),'schema_version':schema['schema_version'],'seed_mode':seed_mode,'batch_mode':batch_mode}

ALLOWED_LORA_NODE={'LoraLoader':('model','clip'), 'LoraLoaderModelOnly':('model',)}
def compile_lora_graph(graph,bindings,selections,available):
 """Offline ComfyUI DAG transformation, NOT proof of installed worker/runtime support.

 bindings: {lora_id: node_id}; explicit allowlist, fixed node class, fixed registry filename.
 """
 if not isinstance(graph,dict) or not isinstance(bindings,dict):fail('workflow','Graph or bindings unavailable')
 graph=deepcopy(graph);seen=set();used=set();active=[]
 def bypass(nodeid):
  if nodeid not in graph:fail('workflow.'+nodeid,'Missing LoRA node for bypass')
  node=graph[nodeid];cls=node.get('class_type');ins=node.get('inputs',{})
  if cls not in ALLOWED_LORA_NODE:fail('workflow.'+nodeid,'Cannot bypass unknown node type')
  inputs={name:ins.get(name) for name in ALLOWED_LORA_NODE[cls]}
  if any(not isinstance(v,list) or len(v)!=2 for v in inputs.values()):fail('workflow.'+nodeid,'Cannot safely bypass node')
  for other in graph.values():
   if not isinstance(other,dict):continue
   for k,v in other.get('inputs',{}).items():
    if isinstance(v,list) and len(v)==2 and str(v[0])==nodeid:
     out=str(v[1]);mapping={'0':'model','1':'clip'}
     in_name=mapping.get(out)
     if in_name not in inputs:fail('workflow.'+nodeid,'Unknown LoRA output port')
     other['inputs'][k]=deepcopy(inputs[in_name])
  graph.pop(nodeid)
 for idx,item in enumerate(selections):
  if not isinstance(item,dict) or set(item)!={'id','version','enabled','model_strength','clip_strength','order'}:fail(f'loras.{idx}','Invalid LoRA selection')
  ident=item['id']
  if not isinstance(ident,str) or ident in seen:fail(f'loras.{idx}.id','Duplicate LoRA or invalid ID')
  seen.add(ident)
  if not isinstance(item['enabled'],bool) or not isinstance(item['order'],int) or isinstance(item['order'],bool) or item['order']<0:fail(f'loras.{idx}','Invalid flag/order')
  nodeid=bindings.get(ident)
  if not isinstance(nodeid,str) or nodeid in used or nodeid not in graph:fail(f'loras.{idx}','Missing or duplicate bound LoRA node')
  used.add(nodeid)
  node=graph[nodeid];cls=node.get('class_type');ins=node.get('inputs',{})
  if cls not in ALLOWED_LORA_NODE:fail('workflow.'+nodeid,'Bound node is not a supported LoRA Loader')
  entry=available.get(ident)
  if not entry or entry.get('version')!=item['version']:fail(f'loras.{idx}','LoRA registry version is unavailable')
  for strength in ('model_strength','clip_strength'):
   num=item[strength]
   if isinstance(num,bool) or not isinstance(num,(int,float)) or not math.isfinite(num) or not entry['min_strength']<=num<=entry['max_strength']:fail(f'loras.{idx}.{strength}','LoRA weight out of range')
  if item['enabled']:
   if not entry.get('verified'):fail(f'loras.{idx}','LoRA installation/runtime compatibility not verified')
   ins['lora_name']=entry['logical_name'];ins['strength_model']=item['model_strength']
   if cls=='LoraLoader':ins['strength_clip']=item['clip_strength']
   active.append({'id':ident,'version':item['version'],'order':item['order'],'model_strength':item['model_strength'],'clip_strength':item['clip_strength']})
  else:
   bypass(nodeid)
 # A saved graph may contain enabled-by-default LoRA loader nodes.
 # Unselected slots MUST also be bypassed, rather than using their old weights.
 for nodeid in bindings.values():
  if nodeid not in used:bypass(nodeid)
 if len({x['order'] for x in active})!=len(active):fail('loras','Duplicate LoRA order')
 active.sort(key=lambda v:v['order'])
 if len(active)>1:
  # Do not claim that changing the UI order changes ComfyUI execution order.
  # Phase08 supports a single explicit model-chain; all other requested orders fail closed.
  for prior,nxt in zip(active,active[1:]):
   previous_node=bindings[prior['id']];next_node=bindings[nxt['id']]
   model_link=graph[next_node].get('inputs',{}).get('model')
   if not isinstance(model_link,list) or len(model_link)!=2 or str(model_link[0])!=previous_node:
    fail('loras','Requested LoRA order does not match an actual saved graph model chain','lora_order_unsupported')
 return graph,active


def render_resolved_graph(graph,schema,resolution):
 """Builds a *local* concrete ComfyUI graph. Dispatch requires separate gated Worker integration."""
 from .template import render_template
 variables={}
 for f in schema['fields']:
  key=f.get('variable_key')
  if not key or f['key'] not in resolution['effective']:continue
  value=resolution['effective'][f['key']]
  if f['type']=='seed':value=seed_number(value,'parameters.'+f['key'])
  variables[key]=value
 try:return render_template(graph,variables)
 except KeyError as e:fail('workflow','Missing or unsupported saved graph variable: '+str(e),'workflow_binding_missing')
