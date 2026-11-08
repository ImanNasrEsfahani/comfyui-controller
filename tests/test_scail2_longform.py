"""Long-form processing unit and real-FFmpeg smoke tests; no model or network."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'salad-worker/scail2'))
import longform


def ffprobe_frames(path):
    r=subprocess.run(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
                      '-show_entries','stream=nb_read_frames','-of','csv=p=0',str(path)],
                      check=True,capture_output=True,text=True)
    return int(r.stdout.strip())


class Planner(unittest.TestCase):
    def test_segments_cover_full_length(self):
        for frames in [1,5,6,20,79,80,81,82,83,100,156,157,158,1000,16000]:
            with self.subTest(frames=frames):
                windows=longform.plan(frames/16)
                self.assertEqual(sum(n-drop for _,n,drop in windows),frames)
                self.assertEqual(windows[0][0],0)
                self.assertTrue(all(1<=n<=81 for _,n,_ in windows))
                self.assertTrue(all(drop==5 for _,n,drop in windows[1:]))
    def test_bad_duration(self):
        for val in [-1,0,float('inf'),float('nan')]:
            with self.assertRaises(ValueError):longform.plan(val)
    def test_real_ffmpeg_formats_and_final_frame_count(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);source=d/'input.mov'
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','lavfi','-i',
                            'testsrc=size=320x240:rate=23:duration=8','-c:v','mpeg4',str(source)],
                           check=True,timeout=25)
            windows=longform.plan(8.0)
            parts=[]
            for i,(first,n,drop) in enumerate(windows):
                chunk=d/f'chunk{i}.mp4';processed=d/f'result{i}.mp4'
                longform.extract_window(source,chunk,start_frame=first,frame_count=n,
                                        width=320,height=256)
                self.assertEqual(ffprobe_frames(chunk),81)
                longform.encode_segment(chunk,processed,skip=drop,frame_count=n)
                self.assertEqual(ffprobe_frames(processed),n-drop)
                parts.append(processed)
            output=d/'finished.mp4'
            longform.stitch(parts,source,output,preserve_audio=True,frame_total=128)
            self.assertEqual(ffprobe_frames(output),128)
    def test_mock_comfyui_longform_worker_uses_multiple_windows(self):
        import worker
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);inp=d/'input';inp.mkdir()
            source=d/'source.mov';reference=d/'reference.png'
            subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-y','-f','lavfi','-i',
                            'testsrc=size=320x240:rate=16:duration=8','-c:v','mpeg4',str(source)],
                           check=True,timeout=25)
            reference.write_bytes(b'PNG' + b'0'*200)
            events=[];results=[];prompts=[];active_clip=[None]
            def download(url,path,limit):
                from shutil import copyfile
                copyfile(source if url=='source' else reference,path)
            def make_graph(vid,ref,**kwargs):
                active_clip[0]=inp/vid
                return {'1':{'class_type':'MOCK_GPU','inputs':{}}},{'width':320,'height':256}
            class FakeHB:
                def __init__(self,job,cancel):
                    self.done=threading.Event();self.lost=threading.Event()
                def start(self):pass
                def join(self,timeout=0):pass
            job={'id':'10000000-0000-0000-0000-000000000001',
                'source_ext':'.mov','reference_ext':'.png', 'source_size_bytes':source.stat().st_size,
                'quality':'quality','steps':24,'seed':1,'detect_prompt':'person','prompt':'',
                'preserve_audio':False,'source_url':'source','reference_url':'ref','lease_token':'mock',
                'longform':True}
            with patch.object(worker,'INPUT_DIR',inp),patch.object(worker,'Heartbeat',FakeHB), \
                 patch.object(worker,'download',side_effect=download), \
                 patch.object(worker,'runtime_ready',return_value=[]), \
                 patch.object(worker,'make_graph',side_effect=make_graph), \
                 patch.object(worker,'post_graph',side_effect=lambda graph:prompts.append(graph) or 'mock'), \
                 patch.object(worker,'wait_graph',side_effect=lambda pid,flag:active_clip[0]), \
                 patch.object(worker,'event_update',side_effect=lambda job,state,*a:events.append(state)), \
                 patch.object(worker,'backend',return_value={'url':'https://r2.example.invalid'}), \
                 patch.object(worker,'upload_file',side_effect=lambda url,path:results.append(ffprobe_frames(path))):
                worker.handle(job)
            self.assertEqual(len(prompts),2)
            self.assertEqual(results,[128])
            self.assertEqual(events,['preparing','running','uploading','succeeded'])

    def test_migration_contains_upload_session_table(self):
        self.assertIn('cr_upload_sessions',(ROOT/'scripts/migrate_scail2.py').read_text())
        self.assertIn('character_upload_router',(ROOT/'backend/app/integrated_main.py').read_text())
    def test_frontend_uses_direct_parts(self):
        source=(ROOT/'frontend/src/pages/video/CharacterReplacementPage.jsx').read_text()
        for snippet in ['/uploads/start','/part-url','/complete','part.headers.get(\'ETag\')']:
            self.assertIn(snippet,source)

if __name__=='__main__':unittest.main()
