"""Observed HDFC bank mandate and UPI alerts; never parse balances as amounts."""
import re
from datetime import datetime
from decimal import Decimal

INFO={'id':'hdfc.bank-alert','name':'HDFC Bank mandate / UPI debit and credit alerts','version':'1.0.0','senders':['alerts@hdfcbank.bank.in'],'account_type':'bank'}
MONEY=r'([\d,]+\.\d{2})'
MANDATE=re.compile(r'Rs\.?\s*'+MONEY+r' has been debited from HDFC Bank Account Number [Xx*]*(\d{4}) towards (.{1,300}?) with UMRN ([A-Za-z0-9]+) on (\d{2}-[A-Za-z]{3}-\d{4})\.',re.I)
DEBIT=re.compile(r'Rs\.?\s*'+MONEY+r' is debited from your account ending (\d{4}) towards VPA (.{1,300}?) on (\d{2}-\d{2}-\d{2})\. UPI transaction reference no\.:\s*(\d+)\.',re.I)
CREDIT=re.compile(r'Rs\.?\s*'+MONEY+r' has been successfully credited to your HDFC Bank account ending in (\d{4})\. Transaction Details: a\. Date: (\d{2}-\d{2}-\d{2}) b\. Sender: (.{1,300}?) c\. UPI Reference No\.:\s*(\d+)\b',re.I)

def parse(text):
    text=' '.join(text.split())
    results={}
    for pattern,mode in ((MANDATE,'mandate'),(DEBIT,'debit'),(CREDIT,'credit')):
        for match in pattern.finditer(text):
            amount,suffix,a,b,c=match.groups()
            if mode=='mandate':description=f'{a} · UMRN {b}';day=c;fmt='%d-%b-%Y'
            elif mode=='debit':description=f'UPI {a} · Ref {c}';day=b;fmt='%d-%m-%y'
            else:description=f'UPI credit from {b} · Ref {c}';day=a;fmt='%d-%m-%y'
            date=datetime.strptime(day,fmt).date().isoformat()
            value=Decimal(amount.replace(',',''))
            if not value.is_finite() or value<=0:raise ValueError('Invalid HDFC transaction amount.')
            signed=float(value if mode=='credit' else -value)
            result=dict(date=date,time='00:00:00',amount=signed,description=description,kind='credit' if mode=='credit' else 'expense',account_last4=suffix,issuer='hdfc',account_type='bank',note='Bank alert, not a verified statement entry. Email supplies no transaction time; 00:00:00 is a placeholder. Credits are not assumed to be salary or refunds. Review transfers and reconcile with the statement.')
            results[(date,suffix,signed,description)]=result
    if len(results)!=1:raise ValueError('No single supported HDFC bank transaction was found.')
    return next(iter(results.values()))
