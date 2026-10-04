import re
from datetime import datetime
from decimal import Decimal

INFO = dict(id='idfc.neft-credit', name='IDFC FIRST Bank incoming NEFT alerts', version='1.0.0',
            senders=['transaction.alerts@idfcfirstbank.com'], account_type='bank')


def parse(text):
    text = ' '.join(text.split())
    pattern = r'Your A/C\s+[Xx*]*(\d{4}) has been credited with INR ([\d,]+\.\d{2}) on (\d{2}-\d{2}-\d{4}) (\d{2}:\d{2}:\d{2}) vide NEFT payment reference ([A-Za-z0-9]+) received from (.{1,300}?)\.\s*New balance'
    matches = {m.groups() for m in re.finditer(pattern, text, re.I)}
    if len(matches) != 1:
        raise ValueError('No single incoming NEFT credit found.')
    suffix, amount, day, clock, reference, sender = next(iter(matches))
    stamp = datetime.strptime(day + ' ' + clock, '%d-%m-%Y %H:%M:%S')
    value = Decimal(amount.replace(',', ''))
    if not value.is_finite() or value <= 0:
        raise ValueError('Invalid amount.')
    return dict(date=stamp.date().isoformat(), time=clock, amount=float(value),
                description=f'NEFT credit from {sender} · Ref {reference}', kind='credit',
                account_last4=suffix, issuer='idfc', account_type='bank',
                note='Incoming NEFT credit. Sender and reference are supplied; salary is not inferred. Use your category rules or edit to classify income.')
