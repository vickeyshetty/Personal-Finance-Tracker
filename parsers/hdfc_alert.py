import re
from datetime import datetime
from decimal import Decimal

INFO={'id':'hdfc.card-alert','name':'HDFC credit-card debit alerts','version':'1.0.0','senders':['alerts@hdfcbank.bank.in'],'account_type':'credit_card'}

def parse(text):
    pattern=r'Rs\.?\s*([\d,]+\.\d{2})\s+has been debited from your HDFC Bank Credit Card ending\s+(\d{4})\s+towards\s+(.{1,300}?)\s+on\s+(\d{1,2}\s+[A-Za-z]{3},\s*\d{4})\s+at\s+(\d{2}:\d{2}:\d{2})\s*\.'
    matches={m.groups() for m in re.finditer(pattern,text,re.I)}
    if len(matches)!=1: raise ValueError('No single supported HDFC card debit was found.')
    amount,suffix,merchant,day,clock=next(iter(matches))
    timestamp=datetime.strptime(re.sub(r'\s+',' ',day)+' '+clock,'%d %b, %Y %H:%M:%S')
    value=Decimal(amount.replace(',',''))
    if not value.is_finite() or value<=0: raise ValueError('Invalid amount.')
    return dict(date=timestamp.date().isoformat(),time=clock,amount=-float(value),description=merchant.strip(),kind='expense',
        card_last4=suffix,account_last4=suffix,issuer='hdfc',account_type='credit_card',
        note='Card debit alert, not a settled statement. Merchant is supplied by the email; reconcile with the statement later.')
