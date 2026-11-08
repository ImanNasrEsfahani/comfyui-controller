"""Streaming-friendly SCAIL-2 fixed-window video operations.

Important: windows are independent ComfyUI prompts. The input carries 5 source
frames of overlap; this is NOT the same as anchoring using 5 previous *generated*
frames. For best long-form temporal identity, add persistent generated-frame
conditioning or adopt the upstream Infinity/GAP approach after GPU validation.
"""
from __future__ import annotations

import math
from pathlib import Path
import subprocess

FPS=16
WINDOW=81
OVERLAP=5
STRIDE=WINDOW-OVERLAP


def plan(duration_seconds):
    if not math.isfinite(duration_seconds) or duration_seconds<=0:
        raise ValueError('Source video has no valid finite duration')
    n=max(1,math.ceil(duration_seconds*FPS))
    windows=[]
    start=0
    while start<n:
        frames=min(WINDOW,n-start)
        drop=OVERLAP if start else 0
        if frames<=drop:raise RuntimeError('Invalid overlapping window')
        windows.append((start,frames,drop))
        if start+frames>=n:break
        start+=STRIDE
    if sum(frames-drop for _,frames,drop in windows)!=n:
        raise RuntimeError('Window planner dropped or duplicated frames')
    return windows


def run_ffmpeg(args,*,timeout=1800):
    proc=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',*map(str,args)],
                        check=True,timeout=timeout,capture_output=True)
    return proc


def extract_window(source,dest,*,start_frame,frame_count,width,height):
    if not 1<=frame_count<=WINDOW:raise ValueError('Invalid window')
    if width%32 or height%32:raise ValueError('Invalid normalized dimensions')
    # Accurate input seek into source; fps filter regularizes VFR footage.
    # tpad handles a fractional final frame without shortening the output.
    run_ffmpeg(['-ss',f'{start_frame/FPS:.6f}','-i',source,'-map','0:v:0',
        '-vf',f'fps={FPS},tpad=stop_mode=clone:stop_duration=6,scale={width}:{height}:flags=lanczos,setsar=1',
        '-frames:v',str(WINDOW),'-an','-c:v','libx264','-preset','veryfast','-crf','17',
        '-pix_fmt','yuv420p',dest],timeout=600)
    if not dest.is_file() or dest.stat().st_size<1000:raise RuntimeError('Normalized video chunk is empty')


def encode_segment(source,dest,*,skip,frame_count):
    # Remove repeated 5-frame conditioning overlap from each subsequent output.
    # Identical settings across chunks allow concatenation with -c copy.
    if skip<0 or frame_count<=skip:raise ValueError('Invalid segment trim')
    run_ffmpeg(['-i',source,'-map','0:v:0','-vf',
        f'trim=start_frame={skip}:end_frame={frame_count},setpts=PTS-STARTPTS',
        '-fps_mode','cfr','-r',str(FPS),'-an','-c:v','libx264','-preset','medium',
        '-crf','16','-pix_fmt','yuv420p','-video_track_timescale','16384',dest],timeout=600)
    if not dest.is_file() or dest.stat().st_size<1000:raise RuntimeError('Rendered chunk was empty')


def stitch(parts,source,final,*,preserve_audio,frame_total):
    if not parts:raise ValueError('No rendered parts')
    list_file=final.with_suffix('.concat.txt')
    video=final.with_suffix('.video.mp4')
    # Filenames are generated internally inside the worker's private /tmp.
    list_file.write_text(''.join('file '+repr(str(p.resolve()))+'\n' for p in parts))
    try:
        run_ffmpeg(['-f','concat','-safe','0','-i',list_file,'-an','-c:v','copy',video],timeout=1800)
        args=['-i',video]
        if preserve_audio:args+=['-i',source]
        args+=['-map','0:v:0']
        if preserve_audio:args+=['-map','1:a:0?']
        args+=['-t',f'{frame_total/FPS:.6f}','-c:v','copy','-movflags','+faststart']
        if preserve_audio:args+=['-c:a','aac','-b:a','192k']
        else:args+=['-an']
        args+=[final]
        run_ffmpeg(args,timeout=1800)
        if not final.is_file() or final.stat().st_size<1000:raise RuntimeError('Final video empty')
    finally:
        video.unlink(missing_ok=True)
        list_file.unlink(missing_ok=True)
