import re
from datetime import datetime
from decimal import Decimal

INFO={'id':'indusind.card-alert','name':'IndusInd approved card purchases','version':'1.0.0','senders':['transactionalert@indusind.com'],'account_type':'credit_card'}

def parse(text):
    pattern=r'The transaction on your IndusInd Bank Credit Card ending\s+(\d{4})\s+for INR\s+([\d,]+\.\d{2})\s+on\s+(\d{2}-\s*\d{2}-\s*\d{4})\s+(\d{1,2}:\d{2}:\d{2}\s*[ap]m)\s+at\s+(.{1,300}?)\s+is\s+Approved\.'
    matches={m.groups() for m in re.finditer(pattern,text,re.I)}
    if len(matches)!=1: raise ValueError('Could not identify one approved purchase in this email. Declined, ambiguous or different templates remain in review.')
    suffix,amount,day,clock,description=next(iter(matches))
    timestamp=datetime.strptime(re.sub(r'\s+','',day)+' '+re.sub(r'\s+','',clock),'%d-%m-%Y %I:%M:%S%p')
    value=Decimal(amount.replace(',',''))
    if not value.is_finite() or value<=0: raise ValueError('Invalid alert amount.')
    return dict(date=timestamp.date().isoformat(),time=timestamp.strftime('%H:%M:%S'),amount=-float(value),description=description.strip(),
        kind='expense',card_last4=suffix,account_last4=suffix,issuer='indusind',account_type='credit_card',
        note='Approved authorization, not a settled statement entry. Available credit is not spending. Reconcile with a statement; the settled amount/date can differ.')
