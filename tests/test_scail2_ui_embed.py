"""SCAIL-2 Video Editor integration smoke tests (no GPU / network required)."""
from pathlib import Path
import ast
import importlib.util
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

class VideoEditEmbeddingTests(unittest.TestCase):
    def test_page_keeps_existing_features_and_embeds_character_editor(self):
        text = (ROOT / 'frontend/src/pages/video/VideoPages.jsx').read_text(encoding='utf8')
        self.assertIn('export function VideoCreatePage()', text)
        self.assertIn('export function PrivateVideoPlayer(', text)
        self.assertIn('export function VideoEditPage()', text)
        self.assertIn("import {CharacterReplacementPage} from './CharacterReplacementPage.jsx'", text)
        self.assertIn('<CharacterReplacementPage />', text)
        self.assertIn('جایگزینی شخصیت', text)
        self.assertNotIn('هیچ Workflow و Model ویدئو‌ادیت', text)
        self.assertNotIn('to="/edit/video/character"', text)

    def test_alias_redirect_without_adding_auth_unsafe_path(self):
        text = (ROOT / 'frontend/src/auth/routeUtils.js').read_text(encoding='utf8')
        self.assertIn("normalized === '/edit/video/character'", text)
        self.assertIn("return {scope:'redirect', to:'/edit/video'}", text)
        self.assertNotIn("'/edit/video/character', '/jobs'", text)

    def test_backend_docker_provides_ffprobe(self):
        text = (ROOT / 'backend/Dockerfile').read_text()
        self.assertIn('apt-get install -y --no-install-recommends ffmpeg', text)
        self.assertIn('COPY app ./app', text)

    def test_backend_integrated_router_registered_in_simulation(self):
        """Run real integrated_main against isolated FastAPI stub routers."""
        try:
            from fastapi import FastAPI, APIRouter
        except ImportError:
            self.skipTest('FastAPI must be installed for route integration smoke test')
        name='_scail2_v5_smoke'
        pkg=types.ModuleType(name)
        pkg.__path__=[]
        sys.modules[name]=pkg
        names=['main','auth','media_api','owner_api','account_api','registry_api',
               'parameters_api','workflow_api','worker_v11_api','scheduler_v12_api',
               'video_api','character_replace_api','gpu_self_service']
        installed=[]
        def noop(): return {'ok': True}
        try:
            base=FastAPI()
            base.add_api_route('/health',noop,methods=['GET'])
            old=types.ModuleType(name+'.main');old.app=base
            sys.modules[name+'.main']=old;installed.append(name+'.main')
            route_definitions={
                'auth':[('/api/auth/session','GET'),('/api/auth/login','POST')],
                'owner_api':[('/api/jobs','GET'),('/api/jobs','POST')],
                'account_api':[('/api/users/me','GET')],
                'gpu_self_service':[('/api/self-service/gpu','GET'),('/api/self-service/gpu/{action}','POST')],
                'workflow_api':[('/api/legacy-direct/workflows','GET'),('/api/v2/semantic-workflows','GET')],
                'worker_v11_api':[('/api/v2/worker/claim','POST')],
                'video_api':[('/api/v2/video/models','GET')],
                'character_replace_api':[('/api/v2/character-replace/config','GET'),
                                         ('/api/v2/character-replace/jobs','POST')],
            }
            for label in names[1:]:
                stub=types.ModuleType(name+'.'+label)
                stub.router=APIRouter()
                for path,method in route_definitions.get(label,[]):
                    stub.router.add_api_route(path,noop,methods=[method])
                sys.modules[name+'.'+label]=stub;installed.append(name+'.'+label)
            source=ROOT / 'backend/app/integrated_main.py'
            ast.parse(source.read_text(encoding='utf8'))
            spec=importlib.util.spec_from_file_location(name+'.integrated_main',source)
            mod=importlib.util.module_from_spec(spec)
            sys.modules[name+'.integrated_main']=mod;installed.append(name+'.integrated_main')
            spec.loader.exec_module(mod)
            routes={(r.path,m) for r in base.routes for m in getattr(r,'methods',[])}
            self.assertIn(('/api/v2/character-replace/config','GET'),routes)
            self.assertIn(('/api/v2/character-replace/jobs','POST'),routes)
            self.assertIn(('/api/v2/video/models','GET'),routes)
            self.assertTrue(base.state.integrated_owner_api)
        finally:
            for key in installed:sys.modules.pop(key,None)
            sys.modules.pop(name,None)

if __name__=='__main__':unittest.main()
