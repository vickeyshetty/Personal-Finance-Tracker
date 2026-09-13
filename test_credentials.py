import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock
from pdfminer.pdfdocument import PDFPasswordIncorrect
import app
import credential_store
from test_app import LedgerTests


class CredentialTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self)
        self.vault = {}
        self.patches = [
            patch.object(credential_store, 'backend', return_value=object()),
            patch.object(credential_store, 'save', side_effect=lambda k, v: self.vault.update({k: v})),
            patch.object(credential_store, 'read', side_effect=lambda k: self.vault.get(k)),
            patch.object(credential_store, 'remove', side_effect=lambda k: self.vault.pop(k, None)),
        ]
        for p in self.patches: p.start()
        self.headers = {'X-Ledger-Token': app.LOCAL_TOKEN}
        self.url = '/api/accounts/1/statement-password'

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        LedgerTests.tearDown(self)

    def save_password(self):
        return self.client.put(self.url, headers=self.headers, json={'password': 'synthetic-secret'})

    def test_vault_lifecycle_and_database_has_no_secret(self):
        self.assertEqual(self.save_password().status_code, 200)
        self.assertEqual(self.client.get(self.url, headers=self.headers).json(), {'saved': True})
        self.assertNotIn(b'synthetic-secret', app.DB.read_bytes())
        self.assertNotIn('synthetic-secret', self.client.get('/api/bootstrap').text)
        key = next(iter(self.vault))
        self.client.post('/api/accounts/1/settings', data={'name': 'Renamed', 'archived': False})
        self.assertEqual(next(iter(self.vault)), key)
        self.assertEqual(self.client.delete(self.url, headers=self.headers).status_code, 200)
        self.assertEqual(self.vault, {})

    def test_security_guards(self):
        self.assertEqual(self.client.put(self.url, json={'password':'secret'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, headers={**self.headers,'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/bootstrap', headers={'Host':'evil.example'}).status_code, 400)
        self.assertEqual(self.client.get('/api/bootstrap', headers={'Sec-Fetch-Site':'cross-site'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, headers=self.headers).headers['Cache-Control'], 'no-store')

    def test_vault_failure_is_closed(self):
        with patch.object(credential_store, 'save', side_effect=credential_store.VaultUnavailable('Vault unavailable')):
            self.assertEqual(self.save_password().status_code, 503)
        self.assertEqual(self.vault, {})
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM statement_credentials').fetchone()[0],0)

    def test_validation_does_not_echo_password(self):
        r = self.client.put(self.url, headers=self.headers, json={'password': ['synthetic-secret']})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('synthetic-secret', r.text)

    def test_missing_or_wrong_pdf_password_no_import(self):
        data={'account_id':1,'password_account_id':1}
        files={'file':('locked.pdf',b'%PDF-synthetic','application/pdf')}
        self.assertEqual(self.client.post('/api/import',data=data,files=files).status_code,400)
        self.save_password()
        with patch.object(app,'read_statement',side_effect=PDFPasswordIncorrect):
            r=self.client.post('/api/import',data=data,files=files)
            self.assertEqual(r.status_code,400)
            self.assertIn('saved password is incorrect',r.text)
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM imports').fetchone()[0],0)

    def test_password_reaches_preview_and_confirmation(self):
        self.save_password()
        with patch.object(app,'read_statement',return_value=[{'Date':'2026-08-01','Description':'Example','Amount':-10}]) as reader, patch.object(app,'automatic_statement_account',return_value=None) as detect:
            for preview in (True,False):
                r=self.client.post('/api/import',data={'account_id':1,'password_account_id':1,'preview':preview},files={'file':('locked.pdf',b'%PDF-synthetic','application/pdf')})
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(reader.call_args.kwargs['password'],'synthetic-secret')
                self.assertEqual(detect.call_args.kwargs['password'],'synthetic-secret')

    def test_parser_password_propagation(self):
        document=MagicMock()
        document.__enter__.return_value=document
        document.pages=[MagicMock()]
        document.pages[0].extract_text.return_value='GSTIN of SBI Card'
        with patch('pdfplumber.open',return_value=document) as opened, patch.object(app,'sbi_card_pdf_rows',return_value=[]) as parser:
            app.read_statement(b'%PDF', '.pdf', password='synthetic-secret')
            self.assertEqual(opened.call_args.kwargs['password'],'synthetic-secret')
            self.assertEqual(parser.call_args.kwargs['password'],'synthetic-secret')

    def test_account_delete_removes_secret(self):
        self.save_password()
        self.assertEqual(self.client.delete('/api/accounts/1').status_code,200)
        self.assertEqual(self.vault,{})

    @unittest.skipUnless(os.environ.get('LEDGER_PDF_TEST_PYTHON'), 'Set LEDGER_PDF_TEST_PYTHON to a Python with reportlab for encrypted PDF integration test')
    def test_real_encrypted_pdf(self):
        # Synthetic statement, generated only in memory. No customer data or vault writes.
        script = '''import io, sys
from reportlab.pdfgen import canvas
from reportlab.lib.pdfencrypt import StandardEncryption
b=io.BytesIO()
c=canvas.Canvas(b,encrypt=StandardEncryption('synthetic-secret',strength=128))
c.drawString(40,800,'GSTIN of SBI Card')
c.drawString(40,780,'Date Transaction Details Amount')
c.drawString(40,760,'01 Aug 26 EXAMPLE SHOP 125.00 D')
c.save()
sys.stdout.buffer.write(b.getvalue())
'''
        contents = subprocess.check_output([os.environ['LEDGER_PDF_TEST_PYTHON'], '-c', script])
        self.save_password()
        files={'file':('SBI Card Statement_9999_test.pdf',contents,'application/pdf')}
        for preview in (True,False):
            r=self.client.post('/api/import', data={'account_id':1,'password_account_id':1,'preview':preview}, files=files)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['debits'],125)
            self.assertEqual(r.json()['account'],'SBI Card ending 9999')
        r=self.client.post('/api/import',data={'account_id':1},files=files)
        self.assertEqual(r.status_code,400)


if __name__ == '__main__': unittest.main()
