"""SBI purchase notifications; promotional amounts are not transaction amounts."""
import re
from datetime import datetime
from decimal import Decimal

INFO = dict(id='sbi.card-alert', name='SBI Card purchase alerts', version='1.0.0',
            senders=['onlinesbicard@sbicard.com'], account_type='credit_card')


def parse(text):
    text = ' '.join(text.split())
    pattern = r'Rs\.?\s*([\d,]+\.\d{2}) spent on your SBI Credit Card ending (\d{4}) at (.{1,300}?) on (\d{2}/\d{2}/\d{2})\.'
    matches = {m.groups() for m in re.finditer(pattern, text, re.I)}
    if len(matches) != 1:
        raise ValueError('No single SBI purchase found.')
    amount, suffix, merchant, day = next(iter(matches))
    value = Decimal(amount.replace(',', ''))
    if not value.is_finite() or value <= 0:
        raise ValueError('Invalid amount.')
    return dict(date=datetime.strptime(day, '%d/%m/%y').date().isoformat(), time=None,
                amount=-float(value), description=merchant, kind='expense',
                account_last4=suffix, issuer='sbi', account_type='credit_card',
                note='Purchase alert; no transaction time supplied. Reconcile with the statement later.')
