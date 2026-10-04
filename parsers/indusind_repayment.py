import re
from datetime import datetime
from decimal import Decimal

INFO = dict(id='indusind.card-repayment', name='IndusInd card repayment confirmations', version='1.0.0',
            senders=['transactionalert@indusind.com'], account_type='credit_card')


def parse(text):
    text = ' '.join(text.split())
    pattern = r'Thank you for your Payment of INR ([\d,]+\.\d{2}) towards your IndusInd Bank Credit Card\. Your payment is credited to your Credit Card account on (\d{2}/\d{2}/\d{4})\.'
    matches = {m.groups() for m in re.finditer(pattern, text, re.I)}
    if len(matches) != 1:
        raise ValueError('No single repayment confirmation found.')
    amount, day = next(iter(matches))
    value = Decimal(amount.replace(',', ''))
    if not value.is_finite() or value <= 0:
        raise ValueError('Invalid amount.')
    return dict(date=datetime.strptime(day, '%d/%m/%Y').date().isoformat(), time=None,
                amount=float(value), description='IndusInd credit card payment received', kind='repayment',
                account_last4='', issuer='indusind', account_type='credit_card',
                note='Repayment, not a refund or income. No card number is supplied: choose the destination card for this email. This will not create an automatic account mapping.')
