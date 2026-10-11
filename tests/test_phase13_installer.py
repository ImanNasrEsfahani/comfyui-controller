import importlib.util,pytest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/phase13_prepare_checkout.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASE="from .scheduler_v12_api import router as scheduler_v12_router\napp.include_router(scheduler_v12_router)\n"
def test_stitch():
 s=m.stitch(BASE)
 assert s.count('video_v13_router')==2
 assert 'from .video_api import router as video_v13_router' in s
 assert s.index('app.include_router(scheduler_v12_router)')<s.index('app.include_router(video_v13_router)')

def test_replay_refused():
 with pytest.raises(RuntimeError,match='already applied'):m.stitch(m.stitch(BASE))

def test_changed_previous_anchor_refused():
 with pytest.raises(RuntimeError,match='anchor changed'):m.stitch('app = None\n')

def test_no_fake_git_checkout(tmp_path):
 with pytest.raises(RuntimeError,match='Complete Git checkout required'):m.prepare(tmp_path,tmp_path)

def test_exact_sha_pinned():assert m.BASE=='a5a22d616558092e3e81504f9ed5d7061f5e0698'
