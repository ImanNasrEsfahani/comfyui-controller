"""No GPU, no network; security-focused golden synthetic semantic compiler tests."""
import unittest,copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.workflow_compiler import validated,compile_graph,preview,CompileError,sha

def node(id,kind):return {'id':id,'kind':kind}
def edge(a,p,b,q):return {'from':a,'out':p,'to':b,'in':q}
def inp(k,kind,role,n,p,required=True):return {'key':k,'type':kind,'role':role,'node':n,'port':p,'required':required}

def sample(intent):
 if intent in ('text2img','img2img','multi_ref'):
  nodes=[node('model','checkpoint'),node('pos','prompt'),node('neg','prompt'),node('sampler','sampler'),node('decode','decode'),node('result','image_output')]
  edges=[edge('model','clip','pos','clip'),edge('model','clip','neg','clip'),edge('model','model','sampler','model'),edge('pos','conditioning','sampler','positive'),edge('neg','conditioning','sampler','negative'),edge('sampler','latent','decode','samples'),edge('model','vae','decode','vae'),edge('decode','image','result','images')]
  inputs=[inp('prompt','text','instruction','pos','text'),inp('negative','text','negative','neg','text'),inp('seed','integer','seed','sampler','seed'),inp('steps','integer','steps','sampler','steps'),inp('cfg','number','cfg','sampler','cfg')]
  if intent=='text2img':
   nodes.append(node('latent','latent'));edges.append(edge('latent','latent','sampler','latent_image'))
   inputs +=[inp('width','integer','width','latent','width'),inp('height','integer','height','latent','height')]
  else:
   nodes +=[node('src','image_input'),node('encoded','encode')]
   edges +=[edge('src','image','encoded','pixels'),edge('model','vae','encoded','vae'),edge('encoded','latent','sampler','latent_image')]
   inputs.append(inp('source_image','image','identity' if intent=='multi_ref' else 'source','src','image'))
  if intent=='multi_ref':
   nodes +=[node('pose','image_input'),node('multiref','multi_reference')]
   edges +=[edge('src','image','multiref','identity'),edge('pose','image','multiref','clothing_pose'),edge('multiref','conditioning','sampler','positive')]
   edges=[e for e in edges if e!=edge('pos','conditioning','sampler','positive')]
   inputs +=[inp('pose_image','image','clothing_pose','pose','image'),inp('instruction','text','edit','multiref','instruction')]
  return {'intent':intent,'nodes':nodes,'edges':edges,'inputs':inputs,'outputs':[{'node':'result','media_type':'image'}]}
 nodes=[node('video','video_generation'),node('final','video_output')]
 edges=[edge('video','frames','final','frames')]
 inputs=[inp('prompt','text','instruction','video','prompt'),inp('seconds','integer','duration','video','seconds'),inp('fps','integer','fps','video','fps')]
 if intent=='image2video':
  nodes.append(node('start','image_input'));edges.append(edge('start','image','video','start_frame'));inputs.append(inp('start_frame','image','start_frame','start','image'))
 return {'intent':intent,'nodes':nodes,'edges':edges,'inputs':inputs,'outputs':[{'node':'final','media_type':'video'}]}

def params(intent):
 v={'prompt':'a tree','negative':'noise','seed':'18446744073709551615','steps':20,'cfg':3.1,'width':1024,'height':768}
 if intent!='text2img':v.pop('width');v.pop('height');v['source_image']='assetA'
 if intent=='multi_ref':v.update(pose_image='assetB',instruction='change coat and pose')
 if intent in ('image2video','text2video'):
  v={'prompt':'pan softly','seconds':4,'fps':24}
  if intent=='image2video':v['start_frame']='assetA'
 return v

class GoldenTests(unittest.TestCase):
 def assertCode(self,code,func):
  with self.assertRaises(CompileError) as x:func()
  self.assertEqual(x.exception.code,code)
 def test_four_golden(self):
  for kind in ['text2img','img2img','multi_ref','image2video','text2video']:
   with self.subTest(kind=kind):
    spec=sample(kind);validated(spec)
    r=compile_graph(spec,params(kind),authorize_asset=lambda s:s in {'assetA','assetB'},model_id='knownmodel')
    self.assertFalse(r['dispatch_allowed']);self.assertEqual(r['graph_hash'],sha(r['graph']))
    self.assertEqual(preview(r)['graph_hash'],r['graph_hash']);self.assertNotIn('a tree',str(preview(r)))
 def test_identity_pose_not_swapped(self):
  r=compile_graph(sample('multi_ref'),params('multi_ref'),authorize_asset=lambda _:True,model_id='knownmodel')
  self.assertEqual(r['graph']['multiref']['inputs']['identity'],['src',0]);self.assertEqual(r['graph']['multiref']['inputs']['clothing_pose'],['pose',0]);self.assertEqual(r['graph']['src']['inputs']['image'],'assetA');self.assertEqual(r['graph']['pose']['inputs']['image'],'assetB')
 def test_malformed_nested_types_are_422_not_500(self):
  for mod in (lambda s:s.update(intent=[]),lambda s:s['nodes'][0].update(kind=[]),lambda s:s['edges'][0].update(**{'from':[]}),lambda s:s['edges'][0].update(out=[]),lambda s:s['inputs'][0].update(node=[]),lambda s:s['outputs'][0].update(node=[])):
   s=sample('text2img');mod(s)
   with self.subTest(mod=repr(mod)):
    with self.assertRaises(CompileError):validated(s)
 def test_unknown_node(self):
  s=sample('text2img');s['nodes'][0]['kind']='ExecutePython';self.assertCode('unknown_node',lambda:validated(s))
 def test_unknown_class_type_key(self):
  s=sample('text2img');s['nodes'][0]['class_type']='Exploit';self.assertCode('invalid_node',lambda:validated(s))
 def test_duplicate_port(self):
  s=sample('text2img');s['edges'].append(edge('neg','conditioning','sampler','positive'))
  self.assertCode('duplicate_binding',lambda:validated(s))
 def test_cycle(self):
  s=sample('text2img')
  s['nodes'].append(node('feedback','encode'))
  s['edges']=[e for e in s['edges'] if not (e['to']=='sampler' and e['in']=='latent_image')]
  s['edges'] += [edge('decode','image','feedback','pixels'),edge('model','vae','feedback','vae'),edge('feedback','latent','sampler','latent_image')]
  self.assertCode('graph_cycle',lambda:validated(s))
 def test_multi_ref_role_binding_must_match_wire(self):
  s=sample('multi_ref');s['inputs']=[dict(i,role='source') if i['role']=='identity' else i for i in s['inputs']]
  self.assertCode('role_binding',lambda:validated(s))
 def test_img2img_source_cannot_be_unbound(self):
  s=sample('img2img');s['inputs']=[dict(i,role='background') if i['role']=='source' else i for i in s['inputs']]
  self.assertCode('role_binding',lambda:validated(s))
 def test_wrong_intent_cannot_fake_multiref(self):
  s=sample('text2img');s['intent']='multi_ref'
  self.assertCode('intent_graph_mismatch',lambda:validated(s))
 def test_unavailable_inpaint_refuses(self):
  s=sample('img2img');s['intent']='inpaint'
  self.assertCode('intent_unavailable',lambda:validated(s))
 def test_invalid_port(self):
  s=sample('text2img');s['edges'][0]['in']='evil';self.assertCode('invalid_port',lambda:validated(s))
 def test_type_mismatch(self):
  s=sample('text2img');s['edges'][0]=edge('model','model','pos','clip');self.assertCode('port_type',lambda:validated(s))
 def test_missing_required_port(self):
  s=sample('text2img');s['edges']=[e for e in s['edges'] if e['to']!='decode'];self.assertCode('missing_port',lambda:validated(s))
 def test_asset_cross_user(self):
  self.assertCode('asset_access_denied',lambda:compile_graph(sample('multi_ref'),params('multi_ref'),model_id='knownmodel',authorize_asset=lambda a:a=='assetA'))
 def test_no_authorizer(self):
  self.assertCode('asset_authorization',lambda:compile_graph(sample('img2img'),params('img2img'),model_id='knownmodel'))
 def test_bad_asset_url(self):
  p=params('img2img');p['source_image']='https://evil.example/asset';self.assertCode('invalid_parameter',lambda:compile_graph(sample('img2img'),p,model_id='m',authorize_asset=lambda _:True))
 def test_reject_overflow_seed(self):
  p=params('text2img');p['seed']='18446744073709551616';self.assertCode('invalid_seed',lambda:compile_graph(sample('text2img'),p,model_id='m'))
 def test_no_float_seed(self):
  p=params('text2img');p['seed']=1.0;self.assertCode('invalid_seed',lambda:compile_graph(sample('text2img'),p,model_id='m'))
 def test_no_extra_param(self):
  p=params('text2img');p['cfg_override']=2;self.assertCode('unsupported_parameter',lambda:compile_graph(sample('text2img'),p,model_id='m'))
 def test_deterministic_hash_different_latest_params(self):
  a=compile_graph(sample('text2img'),params('text2img'),model_id='m');b=compile_graph(sample('text2img'),params('text2img'),model_id='m')
  self.assertEqual(a['graph_hash'],b['graph_hash']);p=params('text2img');p['prompt']='the second prompt';c=compile_graph(sample('text2img'),p,model_id='m')
  self.assertNotEqual(a['graph_hash'],c['graph_hash'])
 def test_strict_graph_keys(self):
  s=sample('text2img');s['worker_token']='abc';self.assertCode('invalid_graph',lambda:validated(s))
 def test_size_cap(self):
  s=sample('text2img');s['nodes']=s['nodes']*20;self.assertCode('graph_size',lambda:validated(s))

if __name__=='__main__':unittest.main()
