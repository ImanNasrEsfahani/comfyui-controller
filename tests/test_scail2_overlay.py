"""Offline smoke tests; no GPU, network, R2 or Salad side effects."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/'salad-worker/scail2'
sys.path.insert(0,str(WORKER))
import workflow
import model_parts
import fetch_workflow


def dummy_graph():
    base={id:{'class_type':cls,'inputs':{}} for id,cls in workflow.REQUIRED.items()}
    for id,cls in {'87':'CLIPTextEncode','11':'LoraLoaderModelOnly','19':'SamplerCustom',
                   '63':'SamplerCustom','211':'VHS_VideoCombine','8':'VHS_VideoCombine',
                   '88':'VHS_VideoCombine','72':'ImageConcatMulti','92':'PreviewImage'}.items():
        base[id]={'class_type':cls,'inputs':{}}
    return base


class WorkflowTests(unittest.TestCase):
    def test_high_quality_dpo_and_no_distill(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'template.json';path.write_text(json.dumps(dummy_graph()))
            prior=workflow.TEMPLATE;workflow.TEMPLATE=path
            try:
                g,meta=workflow.make_graph('scail2-test.mp4','scail2-reference.jpg',
                    source_width=1920,source_height=1080)
            finally:workflow.TEMPLATE=prior
        self.assertEqual(g['188']['inputs']['value'],True)
        self.assertEqual(g['320']['inputs']['strength_model'],1)
        self.assertEqual(g['95']['inputs']['model'],['320',0])
        self.assertEqual(g['18']['inputs']['steps'],24)
        self.assertTrue(g['71']['inputs']['save_output'])
        self.assertEqual(meta['distill_lora'],0)
        self.assertNotIn('211',g)

    def test_fast_uses_lightx2v(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'template.json';path.write_text(json.dumps(dummy_graph()))
            prior=workflow.TEMPLATE;workflow.TEMPLATE=path
            try:g,meta=workflow.make_graph('scail2-test.webm','scail2-reference.png',
                quality='fast',steps=4,source_width=720,source_height=1280)
            finally:workflow.TEMPLATE=prior
        self.assertEqual(g['95']['inputs']['model'],['11',0])
        self.assertIn('rank64',g['11']['inputs']['lora_name'])
        self.assertEqual(meta['distill_lora'],0.8)
        self.assertEqual(meta['width']%32,0)
        self.assertEqual(meta['height']%32,0)

    def test_reject_unsafe_filename(self):
        with self.assertRaises(ValueError):workflow.make_graph('../secret.mp4','scail2-ref.jpg')

    def test_template_checksum_rejects_invalid(self):
        with self.assertRaises(ValueError):fetch_workflow.verify(b'{}')


class ModelManifest(unittest.TestCase):
    def test_all_expected_models_have_destinations(self):
        data=json.loads((WORKER/'models.json').read_text())
        artifacts=data['artifacts']
        self.assertEqual(len(artifacts),7)
        self.assertEqual(len({item['destination'] for item in artifacts}),7)
        for item in artifacts:
            self.assertFalse(item['destination'].startswith('/'))
            self.assertNotIn('..',Path(item['destination']).parts)
            if 'sha256' in item:self.assertEqual(len(item['sha256']),64)

    def test_baked_parts_role_validation(self):
        with self.assertRaises(ValueError):model_parts.slice_file('unknown',0)


class Migration(unittest.TestCase):
    def test_creates_tables_with_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'db.sqlite3'
            con=sqlite3.connect(path);con.execute('CREATE TABLE baseline(x INTEGER)');con.commit();con.close()
            env={**os.environ,'DB_PATH':str(path)}
            migrate=ROOT/'scripts/migrate_scail2.py'
            for _ in range(2):subprocess.run([sys.executable,str(migrate)],check=True,env=env,capture_output=True)
            con=sqlite3.connect(path)
            names={r[0] for r in con.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            con.close()
            self.assertTrue({'baseline','cr_assets','cr_jobs'}<=names)
            self.assertEqual(len(list(Path(directory).glob('*.bak'))),2)

if __name__=='__main__':unittest.main()
