"""SCAIL-2 ComfyUI API graph adapter; only fixed, pinned, reviewed graph nodes.
The upstream API-format template is downloaded at IMAGE BUILD and verified by
Git blob digest. Never accept user-supplied graph/filename/node IDs.
"""
import copy
import json
import math
from pathlib import Path

TEMPLATE = Path(__file__).with_name('scail2_workflow.json')
ALLOWED = {'quality', 'fast'}
REQUIRED = {'3':'CLIPTextEncode','4':'CLIPTextEncode','18':'BasicScheduler',
            '30':'LoadImage','33':'VHS_LoadVideo','85':'SAM3_VideoTrack',
            '86':'CheckpointLoaderSimple','89':'ImageResizeKJv2',
            '91':'SAM3_VideoTrack','95':'ModelSamplingSD3',
            '104':'SCAIL2ColoredMask','114':'WanSCAILToVideo',
            '115':'WanSCAILToVideo','188':'PrimitiveBoolean',
            '204':'easy forLoopEnd','205':'easy forLoopStart',
            '71':'VHS_VideoCombine','74':'DiffusionModelLoaderKJ'}


def dimensions(width, height, short=704):
    if width < 64 or height < 64:
        raise ValueError('Invalid source dimensions')
    # Never upscale the driving clip unnecessarily; native model's 256px
    # minimum still applies to exceptionally small source videos.
    scale = min(1.0, short / min(width,height))
    w = max(256,int(round(width*scale/32))*32)
    h = max(256,int(round(height*scale/32))*32)
    if max(w,h) > 1600:
        ratio = 1600/max(w,h)
        w = max(256,int(round(w*ratio/32))*32)
        h = max(256,int(round(h*ratio/32))*32)
    return w,h


def make_graph(video_name, reference_name, *, quality='quality', steps=24, seed=1,
               detect_prompt='a person', prompt='', source_width=1280,source_height=720, frame_cap=161):
    if quality not in ALLOWED:
        raise ValueError('Unknown SCAIL-2 quality profile')
    if quality=='quality' and not (16<=steps<=32):
        raise ValueError('Quality steps must be 16-32')
    if quality=='fast' and not (4<=steps<=8):
        raise ValueError('Fast steps must be 4-8')
    for name in (video_name,reference_name):
        if not isinstance(name,str) or not name.startswith('scail2-') or '/' in name or '\\' in name or '..' in name:
            raise ValueError('Unsafe local input filename')
    with TEMPLATE.open(encoding='utf-8') as f:
        graph=json.load(f)
    for ident, cls in REQUIRED.items():
        if graph.get(ident,{}).get('class_type')!=cls:
            raise RuntimeError('Pinned template changed: missing or changed '+ident)
    graph=copy.deepcopy(graph)
    w,h=dimensions(source_width,source_height,704 if quality=='quality' else 512)
    graph['30']['inputs']['image']=reference_name
    graph['33']['inputs'].update(video=video_name,force_rate=16,frame_load_cap=frame_cap,
                                 skip_first_frames=0,select_every_nth=1)
    graph['3']['inputs']['text']=prompt
    graph['4']['inputs']['text']=''
    graph['87']['inputs']['text']=detect_prompt
    graph['188']['inputs']['value']=True
    graph['89']['inputs'].update(width=w,height=h)
    graph['85']['inputs']['max_objects']=1
    graph['91']['inputs']['max_objects']=1
    graph['85']['inputs']['detection_threshold']=0.4
    graph['91']['inputs']['detection_threshold']=0.4
    graph['74']['inputs']['model_name']='wan2.1_14B_SCAIL_2_fp16.safetensors'
    graph['18']['inputs']['steps']=steps
    graph['19']['inputs']['noise_seed']=seed
    graph['63']['inputs']['noise_seed']=seed
    # Always apply the published DPO improvement adapter; it is not fabricated/trained here.
    graph['320']={'class_type':'LoraLoaderModelOnly','inputs':{
        'lora_name':'wan2.1_SCAIL_2_DPO_lora_bf16.safetensors',
        'strength_model':1.0,'model':['74',0]}}
    graph['11']['inputs']['model']=['320',0]
    if quality=='quality':
        # Native 24-step sampling, not the 4-step speed distillation adapter.
        graph['95']['inputs']['model']=['320',0]
        graph['18']['inputs']['model']=['320',0]
    else:
        graph['11']['inputs']['lora_name']='Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors'
        graph['11']['inputs']['strength_model']=0.8
        graph['95']['inputs']['model']=['11',0]
        graph['18']['inputs']['model']=['11',0]
    # Avoid writing extra comparison and intermediate videos to disk.
    for ident,node in graph.items():
        if node.get('class_type')=='VHS_VideoCombine':
            node['inputs']['frame_rate']=16
            node['inputs']['crf']=16 if ident=='71' else 20
            node['inputs']['save_output']=(ident=='71')
            if ident=='71':node['inputs']['filename_prefix']='scail2/character-replacement'
    # Remove redundant preview/comparison nodes and their dependencies from dispatch.
    for ident in ('211','72','92','8','88'):
        graph.pop(ident,None)
    return graph,{'width':w,'height':h,'fps':16,'model':'SCAIL-2 fp16','dpo_lora':1.0,
                  'distill_lora':0.8 if quality=='fast' else 0.0}
