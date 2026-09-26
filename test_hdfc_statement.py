import unittest
from unittest.mock import MagicMock, patch
from parsers.hdfc_statement import parse_pages, HEADER
from test_app import LedgerTests
import app

FIRST='HDFC Bank Credit Cards GSTIN: synthetic\n'+HEADER+'\n16/08/2026| 00:00 IGST EXAMPLE (Ref# 123456789) C 13.50 l\n16/08/2026| 20:29 EXAMPLE SHOP C 252.00 l\nPage 1 of 3'
SECOND=HEADER+'\n31/08/2026| 10:37 BPPY CC PAYMENT EXAMPLE + C 1,000.00 l\n01/09/2026| 12:00 MERCHANT REFUND + C 50.00 l\n08/09/2026| 22:18 EMI EXAMPLE C 300.00 l\nTRANSACTIONS TOTAL AMOUNT\n08/09/2026| 22:18 SUMMARY C 300.00 l'

class HdfcStatementTests(unittest.TestCase):
    def test_signs_dates_and_summary(self):
        rows=parse_pages([FIRST,SECOND,'Loan summary\n16/08/2026| 00:00 NOT A TRANSACTION C 999.00 l'])
        self.assertEqual(len(rows),5)
        self.assertEqual([r['Amount'] for r in rows],[-13.5,-252,1000,50,-300])
        self.assertEqual(rows[0]['Date'],'2026-08-16')
        self.assertIn('Ref# 123456789',rows[0]['Description'])
    def test_repeated_real_rows_are_preserved(self):
        row='16/08/2026| 20:29 EXAMPLE SHOP C 252.00 l'
        self.assertEqual(len(parse_pages([HEADER+'\n'+row+'\n'+row])),2)
    def test_bad_dated_row_rejected(self):
        for row in ['16/08/2026| 20:29 EXAMPLE SHOP ???','32/08/2026| 20:29 SHOP C 252.00 l']:
            with self.assertRaises(ValueError):parse_pages([FIRST,HEADER+'\n'+row])
    def test_currency_glyph(self):
        self.assertEqual(parse_pages([FIRST.replace(' C ',' ₹ ')])[0]['Amount'],-13.5)

class HdfcImportTests(unittest.TestCase):
    def setUp(self):LedgerTests.setUp(self)
    def tearDown(self):LedgerTests.tearDown(self)
    def test_pdf_routing_and_preview_preserves_selected_account(self):
        document=MagicMock()
        document.__enter__.return_value.pages=[MagicMock(extract_text=lambda:FIRST),MagicMock(extract_text=lambda:SECOND)]
        with patch('pdfplumber.open',return_value=document):
            response=self.client.post('/api/import',data={'account_id':3,'preview':True},files={'file':('hdfc.pdf',b'synthetic','application/pdf')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(app.bootstrap()['transactions'],[])
        data=response.json()
        self.assertEqual(data['account'],'Card')
        self.assertEqual(len(data['rows']),5)
        self.assertEqual(data['debits'],565.5)
        self.assertEqual(data['credits'],1050)
        self.assertEqual(data['rows'][2]['kind'],'repayment')
        self.assertEqual(data['rows'][3]['kind'],'refund')
    def test_unknown_pdf_is_not_sent_to_indusind(self):
        document=MagicMock();document.__enter__.return_value.pages=[MagicMock(extract_text=lambda:'Unknown statement')]
        with patch('pdfplumber.open',return_value=document),patch.object(app,'cred_indusind_pdf_rows') as other:
            with self.assertRaisesRegex(ValueError,'Unrecognized PDF'):app.read_statement(b'synthetic','.pdf')
            other.assert_not_called()

if __name__=='__main__':unittest.main()
