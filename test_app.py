import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
from fastapi.testclient import TestClient
import app


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.init_db()
        self.client = TestClient(app.app)
        for name, kind in [('Second bank','bank'),('Card','credit_card')]:
            self.client.post('/api/accounts',data={'name':name,'type':kind})

    def tearDown(self):
        self.client.close()
        app.DB = self.original_db
        self.temp.cleanup()

    def upload(self, text, account=1, **extra):
        return self.client.post('/api/import',data={'account_id':account,**extra},files={'file':('test.csv',text.encode(),'text/csv')})

    def test_cash_flow_avoids_card_double_count(self):
        self.upload('Date,Description,Amount\n2026-08-01,Salary,10000\n2026-08-02,Shop,-500\n2026-08-03,CC PAYMENT,-1000\n2026-08-04,Shop refund,100\n2026-08-05,Invest fund,-2000\n2026-08-06,Self move,-3000\n')
        tx=app.bootstrap()['transactions']
        investment=next(c['id'] for c in app.bootstrap()['categories'] if c['name']=='Investments')
        fund=next(t for t in tx if t['description']=='Invest fund')
        self.client.put('/api/transactions/'+str(fund['id']),json={**fund,'category_id':investment})
        transfer=next(t for t in tx if t['description']=='Self move')
        self.client.post('/api/transactions/'+str(transfer['id'])+'/mark-transfer')
        self.upload('Date,Description,Amount\n2026-08-07,Card purchase,-1500\n',account=3)
        f=self.client.get('/api/cash-flow?month=2026-08').json()
        self.assertEqual(f['incoming'],10100)
        self.assertEqual(f['outgoing'],3500)
        self.assertEqual(f['net'],6600)
        self.assertEqual({g['category']:g['amount'] for g in f['outflows']}['Investments'],2000)
        self.assertEqual(self.client.get('/api/cash-flow?month=2026-99').status_code,400)
        self.assertEqual(self.client.get('/api/cash-flow?month=2026-07').json()['count'],0)

    def test_category_removal_and_restart(self):
        cats=app.bootstrap()['categories']; invest=next(c['id'] for c in cats if c['name']=='Investments')
        self.client.post('/api/rules',data={'pattern':'fund','category_id':invest})
        self.upload('Date,Description,Amount\n2026-08-01,Fund purchase,-100\n')
        before=app.bootstrap()['transactions'][0]
        r=self.client.delete('/api/categories/'+str(invest))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['reclassified'],1)
        after=app.bootstrap()['transactions'][0]
        self.assertEqual(after['category'],'Uncategorized');self.assertEqual(after['kind'],before['kind'])
        self.assertEqual(after['raw_hash'],before['raw_hash']);self.assertEqual(after['amount'],-100)
        app.init_db()
        self.assertNotIn('Investments',[c['name'] for c in app.bootstrap()['categories']])
        self.assertFalse(any(r['merchant_pattern']=='fund' for r in self.client.get('/api/rules').json()))
        self.assertEqual(self.client.post('/api/categories',data={'name':'investments'}).status_code,200)
        app.init_db()
        self.assertEqual(sum(c['name'].lower()=='investments' for c in app.bootstrap()['categories']),1)
        self.assertEqual(self.client.post('/api/categories',data={'name':'INVESTMENTS'}).status_code,400)
        core=next(c['id'] for c in cats if c['name']=='Uncategorized')
        self.assertEqual(self.client.delete('/api/categories/'+str(core)).status_code,400)

    def test_badge_management_persists(self):
        before=self.client.get('/api/badges').json()
        upi=next(b for b in before if b['name']=='UPI')
        self.assertEqual(self.client.delete('/api/badges/'+str(upi['id'])).status_code,200)
        app.init_db()
        self.assertFalse(any(b['name']=='UPI' for b in self.client.get('/api/badges').json()))
        self.assertEqual(self.client.post('/api/badges',data={'name':'Subscription','keywords':'Netflix, spotify','whole_word':False}).status_code,200)
        self.client.post('/api/badges',data={'name':'subscription','keywords':'netflix','whole_word':True})
        items=[b for b in self.client.get('/api/badges').json() if b['name'].lower()=='subscription']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['patterns'],['netflix']);self.assertEqual(items[0]['whole_word'],1)
        self.assertEqual(self.client.post('/api/badges',data={'name':'Empty','keywords':', ,'}).status_code,400)

    def test_keyword_rule_specificity_and_edit(self):
        cats={c['name']:c['id'] for c in app.bootstrap()['categories']}
        self.assertEqual(self.client.post('/api/rules',data={'pattern':'shop','category_id':cats['Shopping'],'rule_id':''}).status_code,200)
        self.client.post('/api/rules',data={'pattern':'food shop','category_id':cats['Groceries']})
        self.upload('Date,Description,Amount\n2026-08-01,FOOD SHOP city,-100\n')
        self.assertEqual(app.bootstrap()['transactions'][0]['category'],'Groceries')
        rule=next(r for r in self.client.get('/api/rules').json() if r['merchant_pattern']=='food shop')
        self.client.post('/api/rules',data={'rule_id':rule['id'],'pattern':'market','category_id':cats['Groceries']})
        self.assertFalse(any(r['merchant_pattern']=='food shop' for r in self.client.get('/api/rules').json()))
        self.assertEqual(app.bootstrap()['transactions'][0]['category'],'Groceries')
        self.upload('Date,Description,Amount\n2026-08-02,FOOD SHOP city,-200\n')
        self.assertEqual(app.bootstrap()['transactions'][0]['category'],'Shopping')

    def test_zero_debit_credit(self):
        result=app.normalise_excel_statement([['Transaction Date','Particulars','Debit','Credit'],['01/08/2026','Salary',0,20000]])
        self.assertEqual(result[0]['Amount'],20000)

    def test_month_breakdown_and_food_rule(self):
        self.upload('Date,Description,Amount\n2026-08-01,SWIGGY FOOD,-500\n2026-08-02,Swiggy Instamart,-300\n2026-08-03,Swiggy refund,100\n2026-08-04,CC PAYMENT,-800\n2026-07-02,SWIGGY FOOD,-999\n')
        d=self.client.get('/api/month-breakdown?month=2026-08').json()
        self.assertEqual(d['gross'],800)
        self.assertEqual(d['net'],700)
        self.assertEqual(d['top_category'],'Online food order')
        self.assertEqual(d['online_food']['count'],1)
        self.assertEqual(d['online_food']['gross'],500)
        self.assertEqual(d['online_food']['refunds'],100)
        self.assertEqual(len(d['transactions']),3)
        self.assertEqual(self.client.get('/api/month-breakdown?month=2026-99').status_code,400)

    def test_quick_commerce_and_people_categories(self):
        self.upload('Date,Description,Amount\n2026-08-01,SWIGGYINSTAMARTPVTLTD,-400\n2026-08-02,Zepto,-250\n2026-08-03,Swiggy food,-300\n')
        tx=app.bootstrap()['transactions']
        mapped={t['description']:t['category'] for t in tx}
        self.assertEqual(mapped['SWIGGYINSTAMARTPVTLTD'],'Quick commerce')
        self.assertEqual(mapped['Zepto'],'Quick commerce')
        self.assertEqual(mapped['Swiggy food'],'Online food order')
        self.assertIn('People',[c['name'] for c in app.bootstrap()['categories']])
        with app.conn() as c:
            c.execute("DELETE FROM migrations WHERE name='quick-commerce-v1'")
            c.execute("UPDATE transactions SET category_id=(SELECT id FROM categories WHERE name='Online food order'),kind='refund' WHERE description='Zepto'")
        app.init_db()
        updated=next(t for t in app.bootstrap()['transactions'] if t['description']=='Zepto')
        self.assertEqual(updated['category'],'Quick commerce')
        self.assertEqual(updated['kind'],'refund')

    def test_existing_swiggy_category_migration(self):
        with app.conn() as c:
            c.execute("DELETE FROM migrations WHERE name='swiggy-category-v1'")
            c.execute("INSERT INTO transactions(date,description,amount,account_id,status,raw_hash,kind) VALUES('2026-08-01','PTM SWIGGY',25,1,'excluded','original','transfer')")
        app.init_db()
        t=app.bootstrap()['transactions'][0]
        self.assertEqual(t['category'],'Online food order')
        self.assertEqual(t['kind'],'transfer')
        self.assertEqual(t['status'],'excluded')

    def test_preview_undo_reimport_and_duplicates(self):
        csv='Date,Description,Amount\n2026-08-01,Shop,-150\n'
        self.assertEqual(self.upload(csv,preview=True).status_code,200)
        self.assertEqual(len(app.bootstrap()['transactions']),0)
        first=self.upload(csv).json()
        self.assertEqual(first['created'],1)
        self.assertEqual(self.upload(csv).json()['review'],1)
        self.client.post('/api/imports/'+str(first['import_id'])+'/undo')
        self.assertEqual(len(app.bootstrap()['trash']),1)

    def test_explicit_transfer_and_restore(self):
        self.upload('Date,Description,Amount\n2026-08-31,Move,-5678.25\n')
        self.upload('Date,Description,Amount\n2026-08-31,Receive,5678.25\n2026-08-30,Unrelated,5678.25\n',2)
        self.assertEqual(self.client.post('/api/transactions/1/mark-transfer?match_id=2').json()['linked'],1)
        tx={t['id']:t for t in app.bootstrap()['transactions']}
        self.assertEqual(tx[3]['status'],'active')
        self.client.post('/api/transactions/1/delete');self.client.post('/api/transactions/1/restore')
        self.assertEqual({t['id']:t for t in app.bootstrap()['transactions']}[1]['status'],'excluded')

    def test_current_month_and_refunds(self):
        today=date.today().isoformat()
        self.upload(f'Date,Description,Amount\n{today},Shop,-1000\n{today},Refund,200\n{today},PAYMENT RECEIVED,800\n{today},Unknown credit,50\n2020-01-01,Old,-9999\n',3)
        d=app.dashboard();cards=app.credit_card_spend()
        self.assertEqual(d['total_spend'],800)
        self.assertEqual(cards['total_credits'],200)
        self.assertEqual(cards['repayments'],800)
        self.assertEqual(cards['unclassified_credits'],50)

    def test_edit_fingerprint_and_restart(self):
        self.upload('Date,Description,Amount\n2026-08-01,Shop,-150\n')
        original=app.bootstrap()['transactions'][0]
        body=dict(date='2026-08-02',description='Changed',amount=-175,account_id=1,category_id=original['category_id'],kind='expense')
        self.assertEqual(self.client.put('/api/transactions/1',json=body).status_code,200)
        updated=app.bootstrap()['transactions'][0]
        self.assertNotEqual(original['raw_hash'],updated['raw_hash'])
        self.assertEqual(original['raw_hash'],updated['source_hash'])
        app.init_db()
        self.assertEqual(app.bootstrap()['transactions'][0]['description'],'Changed')
        body['account_id']=999
        self.assertEqual(self.client.put('/api/transactions/1',json=body).status_code,400)

    def test_sbi_email_filename_preserves_selected_account(self):
        from unittest.mock import MagicMock
        document=MagicMock();document.__enter__.return_value.pages[0].extract_text.return_value='GSTIN of SBI Card'
        with patch('pdfplumber.open',return_value=document):
            with app.conn() as c:
                self.assertIsNone(app.automatic_statement_account(c,'gmail-document-1234567890123456_12092026.pdf','.pdf',b'%PDF'))
                self.assertIsNone(c.execute("SELECT id FROM accounts WHERE name='Credit Card'").fetchone())
            with patch.object(app,'read_statement',return_value=[{'Date':'2026-08-01','Description':'Shop','Amount':-100}]):
                response=self.client.post('/api/import',data={'account_id':3},files={'file':('gmail-document-1234567890123456_12092026.pdf',b'%PDF','application/pdf')})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['account'],'Card')
                self.assertEqual(app.bootstrap()['transactions'][0]['account_id'],3)

    def test_header_over_filename(self):
        with patch.object(app,'xlsx_matrix',return_value=[['Date & Time','Description','AMT','Debit / Credit']]):
            with app.conn() as c:
                self.assertEqual(app.automatic_statement_account(c,'hdfc.xlsx','.xlsx',b'')['type'],'credit_card')

    def test_daily_purchases_not_recurring(self):
        self.assertEqual(app.detect_recurring([dict(date=f'2026-08-0{i}',description='Coffee',amount=-100) for i in range(1,4)]),[])

    def test_undo_then_reimport(self):
        csv='Date,Description,Amount\n2026-08-01,Shop,-150\n'
        first=self.upload(csv).json()
        self.client.post('/api/imports/'+str(first['import_id'])+'/undo')
        self.assertEqual(self.upload(csv).json()['created'],1)

    def test_source_duplicate_after_edit(self):
        csv='Date,Description,Amount\n2026-08-01,Shop,-150\n'
        self.upload(csv)
        t=app.bootstrap()['transactions'][0]
        self.client.put('/api/transactions/1',json={**t,'description':'Corrected shop','kind':'expense'})
        self.assertEqual(self.upload(csv).json()['review'],1)

    def test_rename_preserves_routing(self):
        with app.conn() as c: account=app.ensure_account(c,'IDFC Bank')
        self.client.post(f"/api/accounts/{account['id']}/settings",data={'name':'My IDFC savings'})
        with app.conn() as c:
            self.assertEqual(app.ensure_account(c,'IDFC Bank')['id'],account['id'])

    def test_rules_and_move(self):
        cats=app.bootstrap()['categories']; category=next(c['id'] for c in cats if c['name']=='Groceries')
        self.client.post('/api/rules',data={'pattern':'Shop','category_id':category})
        batch=self.upload('Date,Description,Amount\n2026-08-01,Shop,-150\n').json()
        self.assertEqual(app.bootstrap()['transactions'][0]['category_id'],category)
        self.assertEqual(self.client.post(f"/api/imports/{batch['import_id']}/move",data={'account_id':2}).status_code,200)
        self.assertEqual(app.bootstrap()['transactions'][0]['account_id'],2)


if __name__ == '__main__': unittest.main()
