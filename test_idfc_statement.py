import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from parsers import idfc_statement as parser
from test_app import LedgerTests
import app

TEXT = '''CONSOLIDATED STATEMENT
IDFC FIRST BANK LIMITED
STATEMENT PERIOD : 01-SEP-2026 to 30-SEP-2026
SAVINGS ACCOUNT DETAILS FOR A/C : 12345678901
1,000.00 CR 002 001 150.00 500.00 1,350.00 CR
Date and Time Value Date Transaction Details
'''
TABLES = [[parser.HEADER,
    ['', '', 'opening balance', '', '', '', '1,000.00 CR'],
    ['01 Sep 26 12:30', '01 Sep 26', 'UPI/DR/123/\nExample shop', '', '100.00', '', '900.00 CR']],
    [parser.HEADER,
    ['02 Sep 26 12:30', '02 Sep 26', 'NEFT/ABC/Example sender', '', '', '500.00', '1,400.00 CR'],
    ['02 Sep 26 03:00', '02 Sep 26', 'Another purchase', 'REF42', '50.00', '', '1,350.00 CR']]]


def document():
    doc=MagicMock()
    pages=[]
    for i, table in enumerate(TABLES):
        p=MagicMock()
        p.extract_text.return_value=TEXT if i==0 else 'Date and Time Value Date Transaction Details'
        p.extract_words.return_value=[dict(text=t,top=80) for t in ['Date','and','Time']]
        p.width=600;p.height=840
        p.crop.return_value.extract_tables.return_value=[table]
        table_object=SimpleNamespace(extract=lambda table=table:copy.deepcopy(table),rows=[SimpleNamespace(cells=[(0,0,120,100)]*7) for _ in table])
        p.crop.return_value.find_tables.return_value=[table_object]
        p.crop.return_value.chars=[]
        pages.append(p)
    doc.__enter__.return_value.pages=pages
    return doc


class ParserTests(unittest.TestCase):
    def test_description_wraps_preserve_words_and_references(self):
        def glyphs(lines):
            chars=[]
            for y,(text,gap,first_width) in enumerate(lines):
                widths=[first_width]+[(120-gap-first_width)/(len(text)-1)]*(len(text)-1)
                x=0
                for ch,width in zip(text,widths):
                    chars.append(dict(text=ch,x0=x,x1=x+width,top=y*12))
                    x+=width
            return chars
        lines=[('NEFT/REF1234567890/WI',3.87,5),('PRO',95.75,5.34),
               ('LIMITED/HDFC0000000/CONS',3.73,4.45),('OLIDATED ACCOUNT ENTRY',2.74,6.22),
               ('CBX 04HDFC BANK HOUSE',10.75,5.78),('SANDOZ HOUSE',49.74,5.34),
               ('MUMBAI,MAHARASHTRA,400',3.49,6.66),('018,',98.75,4.45)]
        self.assertEqual(parser.description_from_chars(glyphs(lines),120),
            'NEFT/REF1234567890/WIPRO LIMITED/HDFC0000000/CONSOLIDATED ACCOUNT ENTRY CBX 04HDFC BANK HOUSE SANDOZ HOUSE MUMBAI,MAHARASHTRA,400018,')
        for ref in ['111111111111','222222222222']:
            lines=[(f'UPI/DR/{ref}/GROW',7.74,5),('W IN/HDFC/groww.b/Paid Via',8.74,7.55),('Elements',80.75,5.34)]
            self.assertEqual(parser.description_from_chars(glyphs(lines),120),f'UPI/DR/{ref}/GROWW IN/HDFC/groww.b/Paid Via Elements')
        self.assertIsNone(parser.description_from_chars([],120))

    def test_rows_and_wrapping_and_statement_order(self):
        rows=parser.parse_tables(TEXT,TABLES)
        self.assertEqual([r['Amount'] for r in rows],[-100,500,-50])
        self.assertEqual(rows[0]['Date'],'2026-09-01')
        self.assertIn('Example shop',rows[0]['Description'])
        self.assertIn('REF42',rows[-1]['Description'])
        self.assertEqual(parser.parse_document(document().__enter__.return_value),rows)

    def test_incomplete_and_malformed_rows_fail_closed(self):
        cases=[]
        t=copy.deepcopy(TABLES);t[1].pop();cases.append(t)
        t=copy.deepcopy(TABLES);t[0][-1][4]='1.00';cases.append(t)
        t=copy.deepcopy(TABLES);t[0][-1][5]='100.00';cases.append(t)
        t=copy.deepcopy(TABLES);t[0][-1][0]='01 Oct 26 12:30';cases.append(t)
        t=copy.deepcopy(TABLES);t[0][-1][2]=None;cases.append(t)
        t=copy.deepcopy(TABLES);t[0][1][-1]='1,001.00 CR';cases.append(t)
        for tables in cases:
            with self.assertRaises(ValueError):parser.parse_tables(TEXT,tables)
        for text in [TEXT.replace('002 001','001 001'),TEXT.replace('150.00 500.00','151.00 500.00'),TEXT.replace('1,350.00 CR','1,351.00 CR'),TEXT+'SAVINGS ACCOUNT DETAILS FOR A/C : 98765432100']:
            with self.assertRaises(ValueError):parser.parse_tables(text,TABLES)

    def test_ambiguous_table_rejected(self):
        doc=document().__enter__.return_value
        doc.pages[0].crop.return_value.find_tables.return_value=[]
        with self.assertRaises(ValueError):parser.parse_document(doc)


class ImportTests(unittest.TestCase):
    setUp=LedgerTests.setUp
    tearDown=LedgerTests.tearDown

    def test_preview_and_confirm_uses_known_account_without_creating_one(self):
        with app.conn() as c:
            c.execute("INSERT INTO email_account_links VALUES('idfc','bank','8901',1)")
        before=len(app.bootstrap()['accounts'])
        with patch('pdfplumber.open',return_value=document()):
            preview=self.client.post('/api/import',data={'account_id':2,'preview':True},files={'file':('idfc.pdf',b'synthetic','application/pdf')})
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertEqual(app.bootstrap()['transactions'],[])
            self.assertTrue(preview.json()['detected'])
            self.assertEqual(preview.json()['debits'],150)
            self.assertEqual(preview.json()['credits'],500)
            confirmed=self.client.post('/api/import',data={'account_id':2},files={'file':('idfc.pdf',b'synthetic','application/pdf')})
            self.assertEqual(confirmed.status_code,200,confirmed.text)
        self.assertEqual(len(app.bootstrap()['accounts']),before)
        self.assertEqual({t['account_id'] for t in app.bootstrap()['transactions']},{1})

    def test_password_passed_to_reader(self):
        with patch('pdfplumber.open',return_value=document()) as reader:
            self.assertEqual(len(app.read_statement(b'synthetic','.pdf',password='test-only')),3)
        self.assertEqual(reader.call_args.kwargs['password'],'test-only')


if __name__=='__main__':unittest.main()
