import re
from datetime import datetime
from decimal import Decimal

INFO={'id':'idfc.bank-alert','name':'IDFC FIRST Bank debit / credit alerts','version':'1.0.0','senders':['transaction.alerts@idfcfirstbank.com'],'account_type':'bank'}

def parse(text):
    pattern=r'Your A/C\s+[Xx*]*(\d{4})\s+has been (debited|credited) by INR\s+([\d,]+\.\d{2})\s+on\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})(?!\d)'
    matches={m.groups() for m in re.finditer(pattern,text,re.I)}
    if len(matches)!=1: raise ValueError('Could not identify exactly one supported IDFC debit or credit. No transaction was added.')
    suffix,direction,amount,day,clock=next(iter(matches))
    timestamp=datetime.strptime(day+' '+clock,'%d/%m/%Y %H:%M')
    value=Decimal(amount.replace(',',''))
    if not value.is_finite() or value<=0: raise ValueError('Invalid alert amount.')
    debit=direction.lower()=='debited'
    return dict(date=timestamp.date().isoformat(),time=timestamp.strftime('%H:%M:%S'),amount=float(-value if debit else value),
        description='IDFC bank '+('debit' if debit else 'credit')+' alert (merchant not supplied)',
        kind='expense' if debit else 'credit',account_last4=suffix,issuer='idfc',account_type='bank',
        note='This alert does not identify the merchant or purpose. Balance is not the transaction amount. Choose a category/type; confirm against the statement later.')
