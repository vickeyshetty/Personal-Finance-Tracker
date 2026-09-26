import unittest
from parsers import parse_email

SENDER='alerts@hdfcbank.bank.in'
MANDATE='Rs.1000.00 has been debited from HDFC Bank Account Number XXXXXXXXXX1234 towards Example Services/001234 with UMRN HDFC123456 on 15-Sep-2026.'
DEBIT='Rs.99.00 is debited from your account ending 1234 towards VPA shop@bank (Example Shop) on 19-09-26. UPI transaction reference no.: 123456789012.'
CREDIT='Rs.500.00 has been successfully credited to your HDFC Bank account ending in 1234. Transaction Details: a. Date: 25-09-26 b. Sender: EXAMPLE PERSON (VPA: person@bank) c. UPI Reference No.: 987654321012 Need Help?'
class HdfcBankAlertTests(unittest.TestCase):
    def test_observed_formats(self):
        for text,amount,date in [(MANDATE,-1000,'2026-09-15'),(DEBIT,-99,'2026-09-19'),(CREDIT,500,'2026-09-25')]:
            r=parse_email(SENDER,'Alert',text)
            self.assertEqual((r['amount'],r['date'],r['account_last4']),(amount,date,'1234'))
            self.assertEqual(r['parser_id'],'hdfc.bank-alert');self.assertEqual(r['account_type'],'bank')
            self.assertEqual(r['kind'],'credit' if amount>0 else 'expense')
        self.assertIn('987654321012',parse_email(SENDER,'Alert',CREDIT)['description'])
    def test_duplicate_mime_and_real_distinct_transfers(self):
        self.assertEqual(parse_email(SENDER,'Alert',DEBIT+' '+DEBIT)['amount'],-99)
        with self.assertRaises(ValueError):parse_email(SENDER,'Alert',CREDIT+' '+CREDIT.replace('987654321012','111111111111'))
    def test_reject_balance_invalid_and_wrong_sender(self):
        for text in ['The available balance in your account ending XX1234 is Rs. INR 15,773.72 as of 15-SEP-26.',DEBIT.replace('99.00','0.00'),DEBIT.replace('19-09-26','32-09-26'),MANDATE+' '+DEBIT]:
            with self.assertRaises(ValueError):parse_email(SENDER,'Alert',text)
        with self.assertRaises(ValueError):parse_email(SENDER+'.evil.test','Alert',DEBIT)
    def test_card_routing_is_preserved_and_mixed_mail_rejected(self):
        card='Rs. 256.00 has been debited from your HDFC Bank Credit Card ending 5678 towards EXAMPLE SHOP on 14 Sep, 2026 at 12:13:48 .'
        self.assertEqual(parse_email(SENDER,'Alert',card)['parser_id'],'hdfc.card-alert')
        with self.assertRaises(ValueError):parse_email(SENDER,'Alert',card+' '+DEBIT)

if __name__=='__main__':unittest.main()
