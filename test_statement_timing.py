import json
import unittest
from datetime import datetime
import app
import transaction_timing as timing
from test_app import LedgerTests


class StatementTimingTests(unittest.TestCase):
    setUp=LedgerTests.setUp
    tearDown=LedgerTests.tearDown
    upload=LedgerTests.upload

    def email(self):
        self.upload('Date,Description,Amount\n2026-09-01,Example,-100\n')
        t=app.tx_rows()[0]
        with app.conn() as c:
            c.execute("UPDATE transactions SET source_type='email',email_original=? WHERE id=?",(json.dumps({k:t[k] for k in ('date','amount','description','category_id','kind','status')}),t['id']))
            timing.save(c,t['import_id'],dict(date=t['date'],time='10:00:15'))
        return t['id']

    def test_auto_merge_and_undo_restore_alert_time(self):
        tx=self.email()
        result=self.upload('Date,Time,Description,Amount\n2026-09-01,09:59,Example,-100\n').json()
        self.assertEqual(result['reconciled'],1)
        t=app.tx_rows()[0]
        self.assertEqual(t['id'],tx)
        self.assertEqual((t['time_source'],t['statement_time']),('statement','09:59:00'))
        self.assertEqual(self.client.post(f"/api/imports/{result['import_id']}/undo").status_code,200)
        t=app.tx_rows("t.status='active'")[0]
        self.assertEqual(t['time_source'],'transaction')
        self.assertIsNone(t['statement_time'])

    def test_manual_merge_and_date_only_fallback(self):
        tx=self.email()
        result=self.upload('Date,Description,Amount\n2026-09-01 11:12:13,Actual merchant,-100\n').json()
        self.assertEqual(result['review'],1)
        candidate=app.tx_rows("t.status='review'")[0]
        self.assertEqual(candidate['statement_time'],'11:12:13')
        self.assertEqual(self.client.post(f"/api/transactions/{candidate['id']}/reconcile/{tx}").status_code,200)
        self.assertEqual(app.tx_rows('t.id=?',(tx,))[0]['time_source'],'statement')
        self.client.post(f"/api/imports/{result['import_id']}/undo")
        result=self.upload('Date,Description,Amount\n2026-09-01,Example,-100\n').json()
        self.assertEqual(result['reconciled'],1)
        self.assertEqual(app.tx_rows('t.id=?',(tx,))[0]['time_source'],'transaction')

    def test_formats_and_date_only_values(self):
        for value,expected in [('2026-09-01T12:34:56','12:34:56'),('01/09/2026 / 7:32 PM','19:32:00'),('00:00','00:00:00'),('2026-09-01',None),('25:99',None),(46000,None),(46000.5,'12:00:00')]:
            self.assertEqual(timing.statement_clock(value),expected)
        rows=app.normalise_excel_statement([['Date','Time','Description','Amount'],['2026-09-01',0,'Midnight',-1]])
        self.assertEqual(rows[0]['Time'],'00:00:00')
        self.assertEqual(app.parse_date('01/09/2026 / 7:32 PM'),'2026-09-01')
        self.assertEqual(app.parse_date(datetime(2026,9,1,12,30)),'2026-09-01')

    def test_changed_date_does_not_reuse_statement_time(self):
        self.upload('Date,Time,Description,Amount\n2026-09-01,12:34,Example,-100\n')
        t=app.tx_rows()[0]
        self.assertEqual(t['time_source'],'statement')
        with app.conn() as c:c.execute("UPDATE transactions SET date='2026-09-02' WHERE id=?",(t['id'],))
        self.assertIsNone(app.tx_rows()[0]['time_source'])

    def test_legacy_reconciliation_snapshot_defaults(self):
        self.email()
        result=self.upload('Date,Description,Amount\n2026-09-01,Example,-100\n').json()
        with app.conn() as c:
            r=c.execute('SELECT * FROM reconciliations').fetchone()
            for field in ('before_json','after_json'):
                data=json.loads(r[field]);data.pop('statement_time');data.pop('statement_time_date')
                c.execute('UPDATE reconciliations SET '+field+'=? WHERE id=?',(json.dumps(data),r['id']))
        self.assertEqual(self.client.post(f"/api/imports/{result['import_id']}/undo").status_code,200)


if __name__=='__main__':unittest.main()
