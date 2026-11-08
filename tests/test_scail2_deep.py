"""Regression tests for the overlay application, model shards and worker state.
No cloud calls, no side effects on a real repository.
"""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/'salad-worker/scail2'
sys.path.insert(0,str(WORKER))
sys.path.insert(0,str(ROOT/'scripts'))
import apply_scail2_overlay as patcher
import model_parts
import worker


class PatchContract(unittest.TestCase):
    def create_fixture(self,root):
        expected={}
        for rel,old,_,_ in patcher.PATCHES:
            expected.setdefault(rel,[])
            if old not in expected[rel]:expected[rel].append(old)
        for rel,blocks in expected.items():
            p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('\n'.join(blocks),encoding='utf-8')
        return expected

    def test_apply_all_paths_and_repeat_safely(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);self.create_fixture(folder)
            patcher.main(folder)
            r=(folder/'frontend/src/auth/routeUtils.js').read_text()
            self.assertIn("'/edit/video/character'",r)
            self.assertIn('CharacterReplacementPage', (folder/'frontend/src/app/router.jsx').read_text())
            before={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            patcher.main(folder)
            after={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            self.assertEqual(patcher.prepare(folder),{})

    def test_anchor_mismatch_must_not_modify_any_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);self.create_fixture(folder)
            target=folder/'frontend/src/app/router.jsx'
            target.write_text('Unrelated version',encoding='utf-8')
            before={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            with self.assertRaises(RuntimeError):patcher.main(folder)
            after={p:p.read_bytes() for p in folder.rglob('*') if p.is_file()}
            self.assertEqual(before,after)


class VerifiedShard(unittest.TestCase):
    def test_hash_sharded_model_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);content=b'12345678'*3+b'END'
            parts=root/'parts'/'toy';parts.mkdir(parents=True)
            for n in range(4):(parts/f'{n:03d}.part').write_bytes(content[n*8:(n+1)*8])
            entry={'toy':{'role':'toy','destination':'diffusion_models/test.safetensors',
                          'sha256':hashlib.sha256(content).hexdigest()}}
            with patch.object(model_parts,'PART',8),patch.object(model_parts,'ROOT',root/'parts'),\
                 patch.object(model_parts,'TARGET',root/'models'),patch.object(model_parts,'ENTRIES',entry):
                model_parts.validate_parts()
                model_parts.restore()
                self.assertEqual((root/'models'/'diffusion_models/test.safetensors').read_bytes(),content)
                (parts/'003.part').write_bytes(b'WRONG')
                with self.assertRaises(RuntimeError):model_parts.validate_parts()
                (parts/'003.part').unlink()
                with self.assertRaises(RuntimeError):model_parts.validate_parts()


class WorkerCancellation(unittest.TestCase):
    def test_only_confirmed_interruption_returns_success(self):
        def intercepted(url,data=None,**kwargs):
            if url.endswith('/interrupt'):return {}
            return {'prompt-id':{'status':{'status_str':'error','messages':[
                ['execution_interrupted',{'prompt_id':'prompt-id'}]]}}}
        with patch.object(worker,'json_request',side_effect=intercepted):
            self.assertTrue(worker.interrupt_and_confirm('prompt-id',timeout=1))

    def test_error_is_not_claimed_cancelled(self):
        def intercepted(url,data=None,**kwargs):
            if url.endswith('/interrupt'):return {}
            return {'prompt-id':{'status':{'status_str':'error','messages':[]}}}
        with patch.object(worker,'json_request',side_effect=intercepted):
            with self.assertRaises(RuntimeError):worker.interrupt_and_confirm('prompt-id',timeout=1)

    def test_runtime_source_only_has_required_keys(self):
        paths=[ROOT/'.github/workflows/build-scail2-worker.yml',
               ROOT/'salad-worker/scail2/Dockerfile',ROOT/'salad-worker/scail2/start.sh']
        self.assertTrue(all(x.exists() for x in paths))
        docker=paths[1].read_text()
        self.assertIn('model_parts.py verify',docker)
        self.assertIn('SCAIL2_BAKE_MODE',docker)

class DownloadCache(unittest.TestCase):
    def test_checked_download_cache_and_corruption_recovery(self):
        import download_models
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'source.bin';src.write_bytes(b'test-weight'*20_000)
            expected=hashlib.sha256(src.read_bytes()).hexdigest()
            catalog=root/'manifest.json'
            catalog.write_text(json.dumps({'artifacts':[{'role':'test','repo':'fake/model','path':'weight.safetensors',
                'destination':'loras/weight.safetensors','sha256':expected}]}))
            with patch.object(download_models,'MODELS_ROOT',root/'models'), \
                 patch.object(download_models,'CATALOG',catalog), \
                 patch.object(download_models,'hf_hub_download',return_value=str(src)) as downloader:
                download_models.download()
                target=root/'models/loras/weight.safetensors'
                self.assertEqual(target.read_bytes(),src.read_bytes())
                download_models.download()
                self.assertEqual(downloader.call_count,1)
                # A corrupt cached file must never be accepted as a model.
                # The installed copy is hardlinked to source on one filesystem;
                # unlink first so this corruption does not mutate source.
                target.unlink();target.write_bytes(b'corrupted')
                download_models.download()
                self.assertEqual(target.read_bytes(),src.read_bytes())
                self.assertEqual(downloader.call_count,2)

if __name__=='__main__':unittest.main()
