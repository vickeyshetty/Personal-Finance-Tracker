"""Synthetic fixtures matching the observed templates; no personal email data."""
import unittest
from unittest.mock import patch, MagicMock
from parsers import parse_email
import app
import gmail_ingestion as gmail
from test_gmail import GmailTests, mail

SBI = 'Rs.396.00 spent on your SBI Credit Card ending 1234 at EXAMPLESHOP on 30/09/26. Exclusive offer Rs.2500 EMI.'
NEFT = 'Your A/C XXXXXXX1234 has been credited with INR 10,000.00 on 30-09-2026 07:32:03 vide NEFT payment reference REF123456 received from EXAMPLE COMPANY. New balance is INR 25,000.00.'
PAYMENT = 'Thank you for your Payment of INR 1,000.00 towards your IndusInd Bank Credit Card. Your payment is credited to your Credit Card account on 01/10/2026.'
REMINDER = 'There is an upcoming E-mandate (Auto payment) of INR 199.00 for EXAMPLE. Amount will be debited from your HDFC Bank Credit Card ending 1234 on 06/10/2026.'
CASES = [('onlinesbicard@sbicard.com', SBI, -396, 'expense'),
         ('transaction.alerts@idfcfirstbank.com', NEFT, 10000, 'credit'),
         ('transactionalert@indusind.com', PAYMENT, 1000, 'repayment')]


class FormatTests(unittest.TestCase):
    def test_formats_and_repeated_mime(self):
        for sender, text, amount, kind in CASES:
            r = parse_email(sender, 'Alert', text + ' ' + text)
            self.assertEqual((r['amount'], r['kind']), (amount, kind))
        self.assertEqual(parse_email(CASES[1][0], '', NEFT)['time'], '07:32:03')
        self.assertIn('EXAMPLE COMPANY', parse_email(CASES[1][0], '', NEFT)['description'])
        self.assertIsNone(parse_email(CASES[0][0], '', SBI)['time'])
        self.assertEqual(parse_email(CASES[2][0], '', PAYMENT)['account_last4'], '')

    def test_reject_bad_dates_zero_ambiguity_and_wrong_sender(self):
        for sender, text, amount, kind in CASES:
            with self.assertRaises(ValueError): parse_email('evil@bank.example', '', text)
            with self.assertRaises(ValueError): parse_email(sender, '', text.replace('2026','2099').replace('30/09/26','31/09/26').replace('30-09-2099','31-09-2099').replace('01/10/2099','32/10/2099'))
            variant = text.replace('396.00','397.00').replace('10,000.00','10,001.00').replace('1,000.00','1,001.00')
            with self.assertRaises(ValueError): parse_email(sender, '', text + ' ' + variant)
            zero = text.replace('396.00','0.00').replace('10,000.00','0.00').replace('1,000.00','0.00')
            with self.assertRaises(ValueError): parse_email(sender, '', zero)


class IntakeTests(unittest.TestCase):
    setUp = GmailTests.setUp
    tearDown = GmailTests.tearDown

    def configure(self, sender):
        self.config['senders'] = [sender]
        self.client.post('/api/gmail/configure', json=self.config)

    def test_reminder_reclassifies_existing_review_and_creates_no_transaction(self):
        sender = 'alerts@hdfcbank.bank.in'
        message = mail('reminder', sender=sender, pdf=False, text=REMINDER)
        self.configure(sender)
        with app.conn() as c:
            gmail.stage_message(c, 'inbox@example.com', message, [sender])
            c.execute("UPDATE gmail_intake SET status='needs_review',note='Previously unsupported'")
        def get(session, path, params=None):
            return {'messages':[]} if path=='messages' else message
        with patch.object(gmail,'google_client',return_value=MagicMock()), patch.object(gmail,'get_json',side_effect=get):
            result = self.client.post('/api/gmail/sync').json()
        self.assertEqual(result['ignored'], 1)
        self.assertEqual(app.bootstrap()['transactions'], [])
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT status FROM gmail_intake').fetchone()[0], 'ignored')
        mixed = mail(sender=sender,pdf=False,text=REMINDER+' Rs.99.00 has been debited from your card.')
        self.assertEqual(gmail.classify(mixed['payload'],[sender])[2][0][3], 'needs_review')

    def test_repayment_requires_per_email_choice_and_is_excluded(self):
        sender = 'transactionalert@indusind.com'
        self.configure(sender)
        message = mail('repayment',sender=sender,pdf=False,text=PAYMENT)
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',message,[sender])
            item = dict(c.execute('SELECT * FROM gmail_intake').fetchone())
            self.assertEqual(gmail.auto_process_alert(c,item,message['payload']), 'review')
        parsed = gmail.parse_transaction_alert(message['payload'])
        with patch.object(gmail,'read_alert',return_value=parsed):
            preview = self.client.post(f"/api/gmail/items/{item['id']}/alert-preview",json={'account_id':3}).json()
        result = self.client.post(f"/api/gmail/items/{item['id']}/alert-confirm",json=preview)
        self.assertEqual(result.status_code,200,result.text)
        with app.conn() as c:
            tx = c.execute('SELECT * FROM transactions').fetchone()
            self.assertEqual((tx['kind'],tx['status'],tx['amount']),('repayment','excluded',1000))
            self.assertEqual(c.execute("SELECT count(*) FROM email_account_links WHERE last4='' ").fetchone()[0],0)

    def test_new_alerts_use_existing_duplicate_checks(self):
        for i,(sender,text,amount,kind) in enumerate(CASES[:2]):
            self.configure(sender)
            account = 3 if i==0 else 1
            issuer = 'sbi' if i==0 else 'idfc'
            account_type = 'credit_card' if i==0 else 'bank'
            with app.conn() as c:
                c.execute('INSERT INTO email_account_links VALUES(?,?,?,?)',(issuer,account_type,'1234',account))
                for j in range(2):
                    message=mail(f'alert-{i}-{j}',sender=sender,pdf=False,text=text)
                    gmail.stage_message(c,'inbox@example.com',message,[sender])
                    item=dict(c.execute('SELECT * FROM gmail_intake WHERE message_id=?',(message['id'],)).fetchone())
                    self.assertEqual(gmail.auto_process_alert(c,item,message['payload']),'added' if j==0 else 'review')
        self.assertEqual(len(app.bootstrap()['review']),2)


if __name__=='__main__': unittest.main()
