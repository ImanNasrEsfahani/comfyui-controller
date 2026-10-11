from pathlib import Path
import importlib.util,tempfile,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('videopipeline',ROOT/'backend/app/video_pipeline.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
@pytest.fixture(scope='module')
def valid_video():
 with tempfile.TemporaryDirectory(prefix='phase13-media-') as folder:
  path=Path(folder)/'demo.mp4'
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=128x128:rate=10',
    '-t','1','-pix_fmt','yuv420p','-c:v','libx264','-threads','1','-movflags','+faststart','-y',str(path)],check=True,timeout=30)
  yield path

def test_probe_real_mp4(valid_video):
 m=p.probe(valid_video);assert m['container']=='mp4' and m['codec']=='h264' and m['width']==128 and m['duration_seconds']>=.9

def test_wrong_magic(tmp_path):
 path=tmp_path/'fake.mp4';path.write_bytes(b'X'*200)
 with pytest.raises(p.VideoError,match='INVALID_VIDEO_MAGIC'):p.probe(path)

def test_empty_fails(tmp_path):
 path=tmp_path/'empty.mp4';path.write_bytes(b'')
 with pytest.raises(p.VideoError,match='VIDEO_SIZE_INVALID'):p.probe(path)

def test_oversize_limit(valid_video):
 with pytest.raises(p.VideoError,match='VIDEO_SIZE_INVALID'):p.probe(valid_video,max_bytes=32)

def test_duration_limit(valid_video):
 with pytest.raises(p.VideoError,match='VIDEO_DURATION_INVALID'):p.probe(valid_video,max_duration=.1)

def test_derivatives_are_real(valid_video,tmp_path):
 before=valid_video.read_bytes();result=p.derivatives(valid_video,tmp_path)
 assert result['poster_status']=='ready' and result['proxy_status']=='ready'
 assert result['poster_path'].stat().st_size>100
 assert p.probe(result['proxy_path'])['width']<=320
 assert valid_video.read_bytes()==before

def test_proxy_skipped_preserves_original(valid_video,tmp_path):
 before=valid_video.read_bytes();result=p.derivatives(valid_video,tmp_path,make_proxy=False)
 assert result['proxy_status']=='not_requested' and result['poster_status']=='ready'
 assert valid_video.read_bytes()==before

def test_missing_file_fails(tmp_path):
 with pytest.raises(p.VideoError,match='INVALID_VIDEO'):p.probe(tmp_path/'missing.mp4')

POLICY={'runtime_tested':True,'intents':['text2video','image2video'],'dimensions':[[512,512]],
 'fps':[16],'max_seconds':4,'codecs':['h264'],'optional_slots':[]}
PARAMS={'intent':'text2video','prompt':'abc','seconds':3,'fps':16,'width':512,'height':512,'seed':'0','codec':'h264'}
@pytest.mark.parametrize('field,value,code',[
 ('fps',120,'VIDEO_TIMING_UNSUPPORTED'),('seconds',10,'VIDEO_TIMING_UNSUPPORTED'),
 ('codec','mpeg4','VIDEO_CODEC_UNSUPPORTED'),('width',513,'VIDEO_RESOLUTION_UNSUPPORTED'),
 ('seed','18446744073709551616','VIDEO_SEED_INVALID'),('seed',123,'VIDEO_SEED_INVALID'),
 ('prompt','', 'VIDEO_PROMPT_INVALID'),('intent','videoedit','VIDEO_INTENT_UNAVAILABLE'),
 ('start_frame','asset1','VIDEO_FRAME_UNSUPPORTED'),
])
def test_invalid_parameters(field,value,code):
 with pytest.raises(p.VideoError,match=code):p.validate_parameters(POLICY,{**PARAMS,field:value})

def test_unknown_parameter_refused():
 with pytest.raises(p.VideoError,match='UNSUPPORTED_VIDEO_PARAMETER'):p.validate_parameters(POLICY,{**PARAMS,'ffmpeg_options':'-f lavfi'})

def test_unapproved_policy_fails():
 with pytest.raises(p.VideoError,match='VIDEO_RUNTIME_NOT_VERIFIED'):p.validate_parameters({**POLICY,'runtime_tested':False},PARAMS)

def test_valid_text_video():assert p.validate_parameters(POLICY,PARAMS)['fps']==16

def test_frame_owner_and_role():
 params={**PARAMS,'intent':'image2video','start_frame':'owned1'}
 assert p.validate_parameters(POLICY,params,authorize=lambda aid,kind:aid=='owned1' and kind=='image')['start_frame']=='owned1'
 with pytest.raises(p.VideoError,match='VIDEO_ASSET_DENIED'):
  p.validate_parameters(POLICY,params,authorize=lambda aid,kind:False)

def test_required_frame():
 with pytest.raises(p.VideoError,match='VIDEO_START_FRAME_REQUIRED'):
  p.validate_parameters(POLICY,{**PARAMS,'intent':'image2video'})
