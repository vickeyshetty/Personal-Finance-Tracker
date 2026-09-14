import json
import unittest
from test_app import LedgerTests
import app
import custom_parsers as cp
import parsers

TABLE={'id':'custom.test','name':'Test table','kind':'table','columns':{'date':'Day','description':'Merchant','amount':'Value'},'date_format':'%Y-%m-%d','amount_mode':'signed'}
EMAIL={'id':'custom.email','name':'Test email','kind':'email','sender':'alerts@bank.example','issuer':'example','account_type':'bank','contains':'Example debit','pattern':r'Example debit (?P<amount>[\d.]+) on (?P<date>[\d-]+) account (?P<last4>\d{4})','description_fallback':'Bank debit alert','date_format':'%Y-%m-%d','amount_mode':'debit'}

class ParserTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self)
        self.client.headers['X-Ledger-Token']=app.LOCAL_TOKEN
    def tearDown(self): LedgerTests.tearDown(self)
    def test_table_test_save_import_disable(self):
        sample='Day,Merchant,Value\n2026-09-14,Example shop,-256\n'
        result=self.client.post('/api/developer/test',data={'definition':json.dumps(TABLE),'sample_text':sample})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(app.bootstrap()['transactions'],[])
        payload={'definition':TABLE,'test_token':result.json()['test_token'],'enabled':True}
        self.assertEqual(self.client.post('/api/developer/parsers',json=payload).status_code,200)
        self.assertEqual(app.read_statement(sample.encode(),'.csv')[0]['Amount'],-256)
        self.assertEqual(self.client.post('/api/developer/parsers',json={**payload,'definition':{**TABLE,'name':'Changed'}}).status_code,400)
        self.client.post('/api/developer/parsers/custom.test/toggle')
        self.assertEqual(cp.enabled(app),[])
        self.client.delete('/api/developer/parsers/custom.test')
        self.assertEqual(self.client.get('/api/developer/parsers').json()['custom'],[])
    def test_custom_email_and_pdf(self):
        sample='Example debit 256 on 2026-09-14 account 1234'
        self.assertEqual(cp.extract(EMAIL,sample+'\n'+sample)['amount'],-256)
        with self.assertRaises(ValueError): cp.extract(EMAIL,sample+'\nExample debit 300 on 2026-09-14 account 1234')
        d={**EMAIL,'kind':'pdf','pattern':r'(?P<date>\d{4}-\d{2}-\d{2}) (?P<description>Shop) (?P<amount>\d+)'}
        self.assertEqual(cp.extract(d,'Example debit\n2026-09-14 Shop 256')[0]['Amount'],-256)
    def test_invalid_rows_do_not_silently_skip(self):
        with self.assertRaises(ValueError): cp.extract(TABLE,'Day,Merchant,Value\n2026-09-14,Shop,-20\nnot-a-date,Other,-10')
        for value in ['NaN','Infinity','0','0.001']:
            with self.assertRaises(ValueError): cp.amount(value,'signed')
    def test_enabled_email_enters_ingestion_without_builtin_keywords(self):
        import base64
        import gmail_ingestion as gmail
        sample='Example debit 256 on 2026-09-14 account 1234'
        with app.conn() as c:
            c.execute('INSERT INTO custom_parsers VALUES(?,?,1,?)',(EMAIL['id'],json.dumps(EMAIL),cp.digest(EMAIL)))
        payload={'headers':[{'name':'From','value':EMAIL['sender']},{'name':'Subject','value':'Account update'}],'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(sample.encode()).decode()}}
        self.assertEqual(gmail.classify(payload,None)[2][0][3],'needs_review')
        self.assertEqual(gmail.parse_transaction_alert(payload)['amount'],-256)
        self.assertEqual(gmail.classify(payload,['other@example.com'])[2][0][3],'ignored')
    def test_hdfc_alert(self):
        text='We would like to inform you that Rs. 256.00 has been debited from your HDFC Bank Credit Card ending 1234 towards EXAMPLE SHOP on 14 Sep, 2026 at 12:13:48 .'
        parsed=parsers.parse_email('alerts@hdfcbank.bank.in','Transaction alert',text+'\n'+text)
        self.assertEqual((parsed['amount'],parsed['description'],parsed['account_last4']),(-256,'EXAMPLE SHOP','1234'))
        self.assertTrue(parsed['provisional'])
        for sender,body in [('fake@example.com',text),('alerts@hdfcbank.bank.in',text.replace('256.00','0.00')),('alerts@hdfcbank.bank.in',text.replace('14 Sep','32 Sep')),('alerts@hdfcbank.bank.in',text+'\n'+text.replace('256.00','300.00'))]:
            with self.assertRaises(ValueError): parsers.parse_email(sender,'Alert',body)
    def test_api_requires_local_token(self):
        self.client.headers.pop('X-Ledger-Token')
        self.assertEqual(self.client.post('/api/developer/parsers/custom.test/toggle').status_code,403)

if __name__=='__main__': unittest.main()
