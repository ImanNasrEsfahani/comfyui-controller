"""Phase13 bounded local video validation/derivative primitives.

Not an inference runner, not an R2 uploader. Only backend-provided private paths
may be passed in. Never pass untrusted user ffmpeg arguments or download URLs.
"""
from __future__ import annotations
import json, math, os, re, subprocess
from pathlib import Path

MAX_BYTES=256*1024*1024
MAX_DURATION=30.0
MAX_FRAMES=1800
CODECS={'mp4': {'h264','hevc','av1'}, 'webm': {'vp8','vp9','av1'}}
class VideoError(ValueError):
    def __init__(self, code):
        super().__init__(code);self.code=code

def _run(argv,timeout):
    try:
        return subprocess.run(argv,capture_output=True,check=True,timeout=timeout)
    except (OSError,subprocess.SubprocessError) as exc:
        raise VideoError('MEDIA_PROCESSING_FAILED') from exc

def probe(path:Path,*,max_bytes=MAX_BYTES,max_duration=MAX_DURATION):
    path=Path(path)
    if not path.is_file() or path.is_symlink():raise VideoError('INVALID_VIDEO')
    size=path.stat().st_size
    if size<=32 or size>max_bytes:raise VideoError('VIDEO_SIZE_INVALID')
    with path.open('rb') as src:header=src.read(32)
    if b'ftyp' in header[4:16]:container='mp4'
    elif header.startswith(b'\x1aE\xdf\xa3'):container='webm'
    else:raise VideoError('INVALID_VIDEO_MAGIC')
    raw=_run(['ffprobe','-v','error','-show_entries','stream=codec_type,codec_name,width,height,r_frame_rate:format=duration',
              '-of','json',str(path)],timeout=15).stdout
    if len(raw)>65536:raise VideoError('VIDEO_PROBE_TOO_LARGE')
    try:
        parsed=json.loads(raw);streams=parsed['streams'];vs=[s for s in streams if s.get('codec_type')=='video']
        if len(vs)!=1:raise VideoError('VIDEO_STREAM_INVALID')
        v=vs[0];codec=v['codec_name'];width=int(v['width']);height=int(v['height'])
        nums=v['r_frame_rate'].split('/');fps=float(nums[0])/float(nums[1]);duration=float(parsed['format']['duration'])
    except (KeyError,TypeError,ValueError,ZeroDivisionError,IndexError,OverflowError) as exc:
        raise VideoError('VIDEO_METADATA_INVALID') from exc
    if codec not in CODECS[container]:raise VideoError('UNSUPPORTED_VIDEO_CODEC')
    if not (64<=width<=4096 and 64<=height<=4096 and width%2==0 and height%2==0):raise VideoError('VIDEO_DIMENSIONS_INVALID')
    if not (math.isfinite(duration) and 0<duration<=max_duration):raise VideoError('VIDEO_DURATION_INVALID')
    if not (math.isfinite(fps) and 1<=fps<=60 and math.ceil(fps*duration)<=MAX_FRAMES):raise VideoError('VIDEO_FRAMES_INVALID')
    return {'container':container,'mime_type':'video/'+container,'codec':codec,'width':width,'height':height,
            'duration_seconds':round(duration,3),'fps':round(fps,3),'size_bytes':size}

def verify_decodable(path:Path,duration_seconds:float):
    """Decode the entire video stream. FFprobe metadata alone is not integrity proof."""
    if not (isinstance(duration_seconds,(int,float)) and math.isfinite(duration_seconds) and
            0<duration_seconds<=MAX_DURATION):raise VideoError('VIDEO_DURATION_INVALID')
    _run(['ffmpeg','-hide_banner','-loglevel','error','-xerror','-nostdin',
          '-i',str(path),'-map','0:v:0','-f','null','-'],
         timeout=max(30,min(180,round(duration_seconds*6))))
    return True

def derivatives(original:Path,folder:Path,*,make_proxy=True):
    """Safe bounded outputs. A proxy failure does not remove/corrupt original.

    Caller uploads original, poster and proxy separately only after R2 ACK/verify;
    never mark the original available based solely on successful ffmpeg.
    """
    original=Path(original).resolve(strict=True);info=probe(original)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    poster=folder/'poster.jpg';proxy=folder/'proxy.mp4'
    if original in {poster.resolve(),proxy.resolve()}:raise VideoError('INVALID_OUTPUT_PATH')
    poster_ok=False;proxy_ok=False
    try:
        _run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(original),
              '-frames:v','1','-vf','scale=w=320:h=320:force_original_aspect_ratio=decrease',
              '-update','1',str(poster)],timeout=30)
        from PIL import Image
        with Image.open(poster) as im:
            im.verify()
        poster_ok=poster.stat().st_size>100
    except (VideoError,OSError,ValueError):
        poster.unlink(missing_ok=True)
    if make_proxy:
        try:
            _run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(original),
                  '-map','0:v:0','-an','-vf','scale=w=320:h=320:force_original_aspect_ratio=decrease:force_divisible_by=2',
                  '-c:v','libx264','-threads','1','-preset','ultrafast','-crf','30',
                  '-movflags','+faststart',str(proxy)],timeout=max(30,info['duration_seconds']*4))
            probe(proxy,max_bytes=min(MAX_BYTES,32*1024*1024))
            proxy_ok=True
        except (VideoError,OSError,ValueError):
            proxy.unlink(missing_ok=True)
    return {'original':info,'poster_path':poster if poster_ok else None,'proxy_path':proxy if proxy_ok else None,
            'poster_status':'ready' if poster_ok else 'failed',
            'proxy_status':'ready' if proxy_ok else ('failed' if make_proxy else 'not_requested')}

VIDEO_MODES={'text2video','image2video'}
ID=re.compile(r'^[A-Za-z0-9_-]{1,96}$')
def validate_parameters(policy:dict,params:dict,*,authorize=None):
    """Model-owned, explicit bounds only. Without a registered policy fail closed."""
    if not isinstance(policy,dict) or not isinstance(params,dict) or not policy.get('runtime_tested'):
        raise VideoError('VIDEO_RUNTIME_NOT_VERIFIED')
    if set(params)-{'intent','prompt','seconds','fps','width','height','seed','codec','start_frame','end_frame'}:
        raise VideoError('UNSUPPORTED_VIDEO_PARAMETER')
    intent=params.get('intent')
    if intent not in VIDEO_MODES or intent not in policy.get('intents',[]):raise VideoError('VIDEO_INTENT_UNAVAILABLE')
    dimensions=policy.get('dimensions',[])
    if not isinstance(dimensions,list) or not dimensions:raise VideoError('VIDEO_POLICY_INCOMPLETE')
    width=params.get('width');height=params.get('height')
    if type(width)!=int or type(height)!=int or [width,height] not in dimensions:raise VideoError('VIDEO_RESOLUTION_UNSUPPORTED')
    seconds=params.get('seconds');fps=params.get('fps')
    if (type(seconds)!=int or type(fps)!=int or not 1<=seconds<=30 or not 1<=fps<=60 or
        seconds>policy.get('max_seconds',0) or fps not in policy.get('fps',[]) or seconds*fps>MAX_FRAMES):
        raise VideoError('VIDEO_TIMING_UNSUPPORTED')
    codec=params.get('codec')
    if codec not in policy.get('codecs',[]) or codec not in {'h264','vp9'}:raise VideoError('VIDEO_CODEC_UNSUPPORTED')
    prompt=params.get('prompt')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2000:raise VideoError('VIDEO_PROMPT_INVALID')
    seed=params.get('seed')
    if not isinstance(seed,str) or not re.fullmatch(r'0|[1-9][0-9]{0,19}',seed) or int(seed)>2**64-1:
        raise VideoError('VIDEO_SEED_INVALID')
    expected=['start_frame'] if intent=='image2video' else []
    for key in ('start_frame','end_frame'):
        aid=params.get(key)
        if key in expected and not aid:raise VideoError('VIDEO_START_FRAME_REQUIRED')
        if aid:
            if key not in expected and key not in policy.get('optional_slots',[]):raise VideoError('VIDEO_FRAME_UNSUPPORTED')
            if not isinstance(aid,str) or not ID.fullmatch(aid) or authorize is None or not authorize(aid,'image'):
                raise VideoError('VIDEO_ASSET_DENIED')
    return {k:params[k] for k in ('intent','prompt','seconds','fps','width','height','seed','codec','start_frame','end_frame') if k in params}
