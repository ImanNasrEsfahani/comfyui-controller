#!/usr/bin/env python3
"""Dedicated SCAIL-2 Worker for a private, token-authenticated controller lane.
Runs one ComfyUI job at a time. No Salad IMDS or Queue SDK required.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from urllib import request, error
from uuid import uuid4
from workflow import make_graph
from workflow import dimensions
import longform

BACKEND=os.getenv('CHARACTER_REPLACE_BACKEND','').rstrip('/')
TOKEN=os.getenv('CHARACTER_REPLACE_WORKER_TOKEN','')
PORT=int(os.getenv('PORT','3000'))
COMFY='http://127.0.0.1:'+str(PORT)
INPUT_DIR=Path(os.getenv('COMFY_INPUT_DIR','/opt/ComfyUI/input')).resolve()
OUTPUT_DIR=Path(os.getenv('COMFY_OUTPUT_DIR','/opt/ComfyUI/output')).resolve()
STOP=threading.Event()
WORKER_GENERATION=uuid4().hex


def json_request(url,data=None,*,secret=False,timeout=25):
    raw=json.dumps(data).encode() if data is not None else None
    req=request.Request(url,data=raw,method='POST' if raw is not None else 'GET',headers={
        'Content-Type':'application/json','Accept':'application/json',
        **({'X-Character-Worker-Token':TOKEN} if secret else {})})
    with request.urlopen(req,timeout=timeout) as rsp:
        return json.load(rsp)


def backend(path,payload=None):
    return json_request(BACKEND+'/api/v2/character-replace/worker/'+path,payload,secret=True)


def runtime_ready():
    try:
        info=json_request(COMFY+'/object_info')
        required=('WanSCAILToVideo','SCAIL2ColoredMask','SAM3_VideoTrack',
                  'VHS_LoadVideo','VHS_VideoCombine','DiffusionModelLoaderKJ',
                  'ImageResizeKJv2','easy forLoopStart','easy forLoopEnd','MathExpression|pysssss')
        return [x for x in required if x not in info]
    except Exception:return ['ComfyUI is not serving object_info']


def download(url,path,limit):
    tmp=path.with_suffix(path.suffix+'.part')
    size=0
    try:
        with request.urlopen(request.Request(url,method='GET'),timeout=90) as rsp, tmp.open('wb') as out:
            while part:=rsp.read(1024*1024):
                size+=len(part)
                if size>limit:raise ValueError('Input download exceeded its cap')
                out.write(part)
        if size<64:raise ValueError('Empty input download')
        tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)


def duration(path):
    p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                      '-of','default=noprint_wrappers=1:nokey=1',str(path)],
                     capture_output=True,text=True,check=True,timeout=20)
    return float(p.stdout.strip())


def video_dimensions(path):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
                      '-show_entries','stream=width,height','-of','csv=p=0:s=x',str(path)],
                     capture_output=True,text=True,check=True,timeout=20)
    return [int(x) for x in p.stdout.strip().split('x')]


def post_graph(graph):
    info=json_request(COMFY+'/prompt',{'prompt':graph,'client_id':'scail2-'+uuid4().hex},timeout=45)
    if 'error' in info or info.get('node_errors'):
        raise RuntimeError('ComfyUI graph rejected: '+str(info.get('error') or info.get('node_errors'))[:400])
    if not info.get('prompt_id'):
        raise RuntimeError('No ComfyUI prompt ID was returned')
    return info['prompt_id']


def result_file(history):
    outputs=history.get('outputs') or {}
    for _,bundle in outputs.items():
        if not isinstance(bundle,dict):continue
        for name in ('gifs','videos'):
            for asset in bundle.get(name,[]):
                if not isinstance(asset,dict) or not str(asset.get('filename','')).lower().endswith('.mp4'):
                    continue
                if asset.get('type','output')!='output':continue
                folder=(OUTPUT_DIR/str(asset.get('subfolder') or '')).resolve()
                candidate=(folder/str(asset['filename'])).resolve()
                if candidate.is_relative_to(OUTPUT_DIR) and candidate.is_file() and not candidate.is_symlink():
                    return candidate
    raise RuntimeError('No verified MP4 output found in ComfyUI history')


def interrupt_and_confirm(prompt_id, timeout=90):
    """Only acknowledge cancellation after ComfyUI reports interrupted.

    If status cannot be confirmed, leave backend cancel_requested for operator
    intervention, rather than lying that execution stopped.
    """
    json_request(COMFY+'/interrupt',{},timeout=20)
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            data=json_request(COMFY+'/history/'+prompt_id,timeout=10)
        except error.HTTPError as exc:
            if exc.code!=404:raise
            data={}
        record=data.get(prompt_id) if isinstance(data,dict) else None
        if record:
            state=str(record.get('status',{}).get('status_str',''))
            messages=record.get('status',{}).get('messages',[])
            if state in ('interrupted','cancelled') or any(
                isinstance(item,(list,tuple)) and item and item[0]=='execution_interrupted' for item in messages):
                return True
            if state in ('success','error'):
                raise RuntimeError('ComfyUI finished without confirming interrupt')
        time.sleep(3)
    raise TimeoutError('Cancellation NOT confirmed by ComfyUI')


def wait_graph(prompt_id,cancel_flag,max_seconds=7200):
    end=time.monotonic()+max_seconds
    while time.monotonic()<end and not STOP.is_set():
        if cancel_flag.is_set():
            interrupt_and_confirm(prompt_id)
            raise InterruptedError('ComfyUI confirmed interruption')
        try:
            data=json_request(COMFY+'/history/'+prompt_id,timeout=20)
            history=data.get(prompt_id)
            if history:
                if history.get('status',{}).get('status_str')!='success':
                    raise RuntimeError('ComfyUI terminated without success')
                return result_file(history)
        except error.HTTPError as exc:
            if exc.code!=404:raise
        time.sleep(4)
    raise TimeoutError('ComfyUI timeout or shutdown')


def finish_video(generated,source,target,preserve_audio):
    length=min(10.0,duration(source))
    args=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-i',str(generated)]
    if preserve_audio:args.extend(['-i',str(source)])
    args.extend(['-map','0:v:0'])
    if preserve_audio:args.extend(['-map','1:a:0?'])
    args.extend(['-t',str(length),'-c:v','libx264','-preset','medium','-crf','16',
                 '-pix_fmt','yuv420p','-movflags','+faststart'])
    if preserve_audio:args.extend(['-c:a','aac','-b:a','192k'])
    else:args.append('-an')
    args.append(str(target))
    subprocess.run(args,check=True,timeout=600)
    if target.stat().st_size<1024:raise RuntimeError('Encoded output is empty')


def upload_file(url,path):
    # Small, bounded video previews only; full body fits in worker RAM.
    def read_chunks():
        with path.open('rb') as stream:
            while chunk:=stream.read(4*1024*1024):
                yield chunk
    req=request.Request(url,data=read_chunks(),method='PUT',headers={
        'Content-Type':'video/mp4','Content-Length':str(path.stat().st_size)})
    with request.urlopen(req,timeout=1800) as response:
        if response.status not in (200,201,204):raise RuntimeError('Output upload not accepted')


class Heartbeat(threading.Thread):
    def __init__(self,job,cancel):
        super().__init__(daemon=True)
        self.job=job;self.cancel=cancel;self.done=threading.Event();self.lost=threading.Event()
    def run(self):
        while not self.done.is_set():
            try:
                res=backend('heartbeat',{'job_id':self.job['id'],'lease_token':self.job['lease_token']})
                if res.get('cancel_requested'):self.cancel.set()
                # Keep public worker readiness fresh during long video renders.
                backend('hello',{'generation':WORKER_GENERATION,'ready':not bool(runtime_ready())})
            except error.HTTPError as exc:
                if exc.code in (401,403,409):self.lost.set();self.cancel.set();return
            except Exception:pass
            self.done.wait(20)


def event_update(job,state,error_text=''):
    data={'job_id':job['id'],'lease_token':job['lease_token'],'state':state,'error':error_text[:300]}
    return backend('event',data)


def handle(job):
    if job.get('longform'):
        return handle_longform(job)
    job_id=job['id'];cancel=threading.Event();hb=Heartbeat(job,cancel);hb.start()
    prefix='scail2-'+re.sub('[^0-9a-f-]','',job_id)
    video=INPUT_DIR/(prefix+job['source_ext'])
    reference=INPUT_DIR/(prefix+'-reference'+job['reference_ext'])
    final=Path('/tmp')/(prefix+'-result.mp4')
    try:
        try:event_update(job,'preparing')
        except error.HTTPError as exc:
            if exc.code==409:raise InterruptedError('Job no longer active')
            raise
        download(job['source_url'],video,90*1024*1024)
        download(job['reference_url'],reference,15*1024*1024)
        if cancel.is_set():raise InterruptedError('Cancelled during preparation')
        width,height=video_dimensions(video)
        graph,meta=make_graph(video.name,reference.name,quality=job['quality'],steps=job['steps'],
            seed=job['seed'],detect_prompt=job['detect_prompt'],prompt=job['prompt'],
            source_width=width,source_height=height)
        if runtime_ready():raise RuntimeError('Required SCAIL-2 ComfyUI nodes missing')
        prompt_id=post_graph(graph)
        if cancel.is_set():
            interrupt_and_confirm(prompt_id)
            raise InterruptedError('ComfyUI confirmed interruption')
        try:event_update(job,'running')
        except error.HTTPError as exc:
            if exc.code==409:
                interrupt_and_confirm(prompt_id)
                raise InterruptedError('Run interrupted after cancelled state transition')
            raise
        generated=wait_graph(prompt_id,cancel)
        if cancel.is_set():raise InterruptedError('Cancelled during execution')
        try:event_update(job,'uploading')
        except error.HTTPError as exc:
            if exc.code==409:raise InterruptedError('Job no longer active')
            raise
        finish_video(generated,video,final,job['preserve_audio'])
        if cancel.is_set():raise InterruptedError('Cancelled during output finalization')
        upload_file(job['output_put_url'],final)
        if cancel.is_set():raise InterruptedError('Cancelled during upload')
        try:event_update(job,'succeeded')
        except error.HTTPError as exc:
            if exc.code==409:raise InterruptedError('Job was cancelled before finalizing')
            raise
        print('[scail2] completed',job_id,'resolution',meta['width'],meta['height'],flush=True)
    except InterruptedError:
        if not hb.lost.is_set():
            try:event_update(job,'cancelled')
            except Exception:pass
    except Exception as exc:
        print('[scail2] failed job',job_id,'reason',type(exc).__name__,flush=True)
        if not hb.lost.is_set():
            try:event_update(job,'failed',type(exc).__name__+': '+str(exc)[:160])
            except Exception:pass
    finally:
        hb.done.set();hb.join(timeout=4)
        for f in (video,reference,final):f.unlink(missing_ok=True)


def handle_longform(job):
    """Run an arbitrary-duration source as independent, bounded 81-frame prompts.

    The original is retained for audio mux. This path deliberately does not
    load the entire video into a ComfyUI node's RAM/VRAM.
    """
    import tempfile
    job_id=job['id'];cancel=threading.Event();hb=Heartbeat(job,cancel);hb.start()
    prefix='scail2-'+re.sub('[^0-9a-f-]','',job_id)
    src=INPUT_DIR/(prefix+job['source_ext'])
    ref=INPUT_DIR/(prefix+'-reference'+job['reference_ext'])
    final=Path('/tmp')/(prefix+'-result.mp4')
    parts=[]
    try:
        event_update(job,'preparing')
        byte_cap=int(job['source_size_bytes'])
        if byte_cap<64:raise ValueError('Invalid source object size')
        download(job['source_url'],src,byte_cap)
        if src.stat().st_size!=byte_cap:raise RuntimeError('Source size changed after R2 claim')
        download(job['reference_url'],ref,15*1024*1024)
        total_seconds=duration(src)
        windows=longform.plan(total_seconds)
        w,h=video_dimensions(src)
        target_w,target_h=dimensions(w,h,704 if job['quality']=='quality' else 512)
        total_frames=sum(frames-drop for _,frames,drop in windows)
        if runtime_ready():raise RuntimeError('Required SCAIL-2 nodes missing')
        event_update(job,'running')
        # Do not allow a single decoded giant batch into SAM3 or VAE.
        with tempfile.TemporaryDirectory(prefix='scail2-windows-') as td:
            folder=Path(td)
            for i,(first,frames,drop) in enumerate(windows):
                if cancel.is_set() or STOP.is_set():raise InterruptedError('Cancelled before next window')
                clip=INPUT_DIR/(prefix+f'-chunk-{i:05d}.mp4')
                try:
                    longform.extract_window(src,clip,start_frame=first,frame_count=frames,
                                            width=target_w,height=target_h)
                    if cancel.is_set() or STOP.is_set():raise InterruptedError('Cancelled before GPU dispatch')
                    graph,meta=make_graph(clip.name,ref.name,quality=job['quality'],
                        steps=job['steps'],seed=job['seed'],detect_prompt=job['detect_prompt'],
                        prompt=job['prompt'],source_width=target_w,source_height=target_h,
                        frame_cap=81)
                    prompt_id=post_graph(graph)
                    rendered=wait_graph(prompt_id,cancel)
                    part=folder/f'{i:05d}.mp4'
                    longform.encode_segment(rendered,part,skip=drop,frame_count=frames)
                    # ComfyUI has already returned this output; reclaim disk for long runs.
                    rendered.unlink(missing_ok=True)
                    parts.append(part)
                    print('[scail2] finished window',i+1,'of',len(windows),flush=True)
                finally:
                    clip.unlink(missing_ok=True)
            if cancel.is_set() or STOP.is_set():raise InterruptedError('Cancelled before concatenation')
            event_update(job,'uploading')
            longform.stitch(parts,src,final,preserve_audio=job['preserve_audio'],frame_total=total_frames)
        if cancel.is_set() or STOP.is_set():raise InterruptedError('Cancelled before upload')
        fresh=backend('output-url',{'job_id':job['id'],'lease_token':job['lease_token']})
        upload_file(fresh['url'],final)
        if cancel.is_set():raise InterruptedError('Cancelled during upload')
        event_update(job,'succeeded')
        print('[scail2] long-form completed',job_id,'windows',len(windows),flush=True)
    except InterruptedError:
        if not hb.lost.is_set():
            try:event_update(job,'cancelled')
            except Exception:pass
    except Exception as exc:
        print('[scail2] long-form job failed',job_id,type(exc).__name__,str(exc)[:220],flush=True)
        if not hb.lost.is_set():
            try:event_update(job,'failed',type(exc).__name__+': '+str(exc)[:160])
            except Exception:pass
    finally:
        hb.done.set();hb.join(timeout=4)
        for p in (src,ref,final):p.unlink(missing_ok=True)


def main():
    if not BACKEND.startswith('https://') or len(TOKEN)<32:
        raise SystemExit('HTTPS backend and >=32-char private worker token required')
    INPUT_DIR.mkdir(parents=True,exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_: STOP.set())
    while not STOP.is_set():
        try:
            missing=runtime_ready()
            backend('hello',{'generation':WORKER_GENERATION,'ready':not bool(missing)})
            if missing:
                print('[scail2] runtime not ready; no job claimed:',','.join(missing[:5]),flush=True)
                STOP.wait(15)
                continue
            reply=backend('claim',{})
            job=reply.get('job')
            if job:handle(job)
            else:
                if reply.get('blocked'):print('[scail2] claim blocked:',reply['blocked'],flush=True)
                STOP.wait(8)
        except Exception as exc:
            print('[scail2] controller not reachable:',type(exc).__name__,flush=True)
            STOP.wait(12)

if __name__=='__main__':main()
