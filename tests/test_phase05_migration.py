"""Offline Phase05 migration smoke: no live DB, WAL, or R2 access."""
import os,sys,sqlite3,tempfile,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.migrations.phase01 import migrate as phase01
from app.migrations.phase02 import migrate as phase02
from app.migrations.phase05 import migrate as phase05,REVISION
from test_phase02_auth import LEGACY

class Phase05Migration(unittest.TestCase):
    def test_additive_idempotent_on_offline_copy(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'isolated.sqlite'
            with sqlite3.connect(db) as conn:
                conn.executescript(LEGACY)
                phase01(conn);phase02(conn)
                before={table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('jobs','input_assets','job_assets','users')}
                self.assertTrue(phase05(conn));self.assertFalse(phase05(conn))
                after={table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in before}
                self.assertEqual(before,after)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(len(list(conn.execute('PRAGMA foreign_key_check'))),0)
                self.assertIn(REVISION,{r[0] for r in conn.execute('SELECT revision FROM schema_migrations')})
    def test_cli_rejects_unacknowledged_and_preserves_offline_copy(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'db.sqlite'
            with sqlite3.connect(db) as conn:
                conn.executescript(LEGACY)
                phase01(conn);phase02(conn)
            command=[sys.executable,str(ROOT/'scripts/phase05_migrate_copy.py'),'--db-copy',str(db)]
            denied=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(denied.returncode,0)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0],4)
            accepted=subprocess.run(command+['--acknowledge-offline-copy'],capture_output=True,text=True)
            self.assertEqual(accepted.returncode,0,accepted.stderr)
            self.assertIn('integrity=ok',accepted.stdout)
if __name__=='__main__':unittest.main()
