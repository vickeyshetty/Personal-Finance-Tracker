import unittest
from unittest.mock import patch,MagicMock
from datetime import date
from test_app import LedgerTests
from test_gmail import mail
import app
import balances
import gmail_ingestion as gmail

TEXT='The available balance in your account ending XX1234 is Rs. INR 1,000.00 as of 15-SEP-26.'
class BalanceTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self);self.client.headers['X-Ledger-Token']=app.LOCAL_TOKEN
    def tearDown(self):LedgerTests.tearDown(self)
    def capture(self,id='balance',text=TEXT):
        with app.conn() as c:
            gmail.stage_message(c,'test@example.com',mail(id,'alerts@hdfcbank.bank.in',False,text),None)
    def link(self):
        with app.conn() as c:c.execute("INSERT INTO email_account_links VALUES('hdfc','bank','1234',1)")
    def test_capture_is_idempotent_and_not_a_transaction(self):
        self.capture();self.capture()
        with app.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM balance_snapshots').fetchone()[0],1)
        self.assertEqual(app.bootstrap()['transactions'],[])
        self.assertEqual(len(self.client.get('/api/gmail/balances').json()['unlinked']),1)
        self.assertIsNone(balances.parse('evil@example.com',TEXT))
    def test_estimate_statuses_dates_and_older_arrival(self):
        self.capture();self.link()
        self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',b'Date,Description,Amount\n2026-09-15,Same day,-300\n2026-09-16,Shop,-100\n2026-09-17,Income,200\n2026-09-18,CC PAYMENT,-50\n2027-01-01,Future,-500\n','text/csv')})
        self.capture('older',TEXT.replace('15-SEP','14-SEP').replace('1,000.00','9,000.00'))
        with app.conn() as c:
            account=balances.overview(c,date(2026,9,26))['accounts'][0]
            self.assertEqual(account['snapshot']['estimated'],1050)
            self.assertEqual(account['snapshot']['same_day_count'],1)
            self.assertTrue(account['snapshot']['stale'])
            c.execute("UPDATE transactions SET status='review' WHERE description='Shop'")
            c.execute("UPDATE transactions SET status='deleted' WHERE description='Income'")
            s=balances.overview(c,date(2026,9,26))['accounts'][0]['snapshot']
            self.assertEqual(s['estimated'],950);self.assertEqual(s['review_count'],1)
    def test_conflicting_and_future_snapshots_suppress_estimate(self):
        self.capture();self.link();self.capture('conflict',TEXT.replace('1,000.00','2,000.00'))
        with app.conn() as c:self.assertIsNone(balances.overview(c,date(2026,9,26))['accounts'][0]['snapshot']['estimated'])
        self.capture('future',TEXT.replace('15-SEP-26','01-OCT-26'))
        with app.conn() as c:self.assertIsNone(balances.overview(c,date(2026,9,26))['accounts'][0]['snapshot']['estimated'])
    def test_link_requires_bank_and_cannot_remap(self):
        self.capture()
        self.assertEqual(self.client.post('/api/gmail/balances/1/link',json={'account_id':3}).status_code,400)
        self.assertEqual(self.client.post('/api/gmail/balances/1/link',json={'account_id':1}).status_code,200)
        self.assertEqual(self.client.post('/api/gmail/balances/1/link',json={'account_id':2}).status_code,409)
    def test_sender_allowlist_prevents_capture(self):
        with app.conn() as c:
            gmail.stage_message(c,'test@example.com',mail('one','alerts@hdfcbank.bank.in',False,TEXT),['other@example.com'])
            self.assertEqual(c.execute('SELECT count(*) FROM balance_snapshots').fetchone()[0],0)
    def test_imported_pdf_keeps_rule_match(self):
        with app.conn() as c:
            c.execute("INSERT INTO gmail_statement_rules(name,sender,subject_keyword,filename_keyword,account_id) VALUES('HDFC','cards@example.com','statement','',3)")
            r=gmail.statement_route(c,{'status':'imported','filename':'monthly.pdf','sender':'cards@example.com','subject':'Monthly statement'})
            self.assertEqual(r['name'],'HDFC')
    def test_sync_backfills_old_ignored_balance_once(self):
        self.capture()
        with app.conn() as c:
            c.execute('DELETE FROM balance_snapshots')
            c.execute("UPDATE gmail_intake SET balance_checked=0,subject='View: Account update for your HDFC Bank A/c'")
            c.execute("INSERT INTO gmail_settings(id,vault_key,email,start_date,senders,all_senders) VALUES(1,'fake','test@example.com','','[]',1)")
        message=mail('balance','alerts@hdfcbank.bank.in',False,TEXT)
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=lambda session,path,*args: {'messages':[]} if path=='messages' else message):
            response=self.client.post('/api/gmail/sync')
            self.assertEqual(response.status_code,200,response.text)
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM balance_snapshots').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT balance_checked FROM gmail_intake').fetchone()[0],1)
        self.assertEqual(app.bootstrap()['transactions'],[])

if __name__=='__main__':unittest.main()
