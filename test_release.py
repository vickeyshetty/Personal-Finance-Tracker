"""Release smoke checks use synthetic data and temporary databases only."""
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app
import test_app


class ReleaseSmokeTests(unittest.TestCase):
    setUp = test_app.LedgerTests.setUp
    tearDown = test_app.LedgerTests.tearDown

    def test_empty_install_and_all_served_assets(self):
        self.assertEqual(app.bootstrap()['transactions'], [])
        # Initialization must also be safe on an existing installation.
        app.init_db()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for asset in re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text):
            self.assertEqual(self.client.get(asset).status_code, 200, asset)
        self.assertNotIn('/static/salary.js', response.text)
        dashboard = self.client.get('/static/period.js').text
        self.assertNotIn("metric('Salary remaining'", dashboard)
        for label in ('Salary received', 'Spent after refunds', 'Investments'):
            self.assertIn("metric('" + label + "'", dashboard)

    def test_backup_restore_preserves_ledger(self):
        self.client.post('/api/import',data={'account_id':1},files={
            'file':('synthetic.csv',b'Date,Description,Amount\n2026-09-01,Example shop,-125\n','text/csv')})
        before = app.bootstrap()
        with patch.object(app,'ROOT',Path(self.temp.name)):
            response = self.client.get('/api/backup')
        self.assertEqual(response.status_code,200)
        restored = Path(self.temp.name)/'restored.db'
        restored.write_bytes(response.content)
        with closing(sqlite3.connect(restored)) as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(),[])
        with patch.object(app,'DB',restored):
            app.init_db()
            self.assertEqual(app.bootstrap(),before)


if __name__ == '__main__':
    unittest.main()
