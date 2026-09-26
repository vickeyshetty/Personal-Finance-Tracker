"""HDFC card PDF transaction tables. The extracted C glyph is a rupee symbol."""
import re
from datetime import datetime
from decimal import Decimal

HEADER = 'DATE & TIME TRANSACTION DESCRIPTION AMOUNT PI'
ROW = re.compile(r'^(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}:\d{2})\s+(.+?)\s+(\+\s*)?(?:C|₹|INR|Rs\.?)\s*([\d,]+\.\d{2})(?:\s+[l●•])?$')

def matches(text):
    return bool(re.search(r'HDFC\s+Bank\s+Credit\s+Cards', text, re.I))

def parse_pages(pages):
    rows=[]
    for text in pages:
        active=False
        for raw in text.splitlines():
            line=' '.join(raw.split())
            if line.upper()==HEADER:
                active=True
                continue
            if line.startswith(('Page ', 'TRANSACTIONS TOTAL AMOUNT', 'Reward Points', 'REWARD POINTS')):
                active=False
            if not active or not re.match(r'^\d{2}/\d{2}/\d{4}',line):
                continue
            match=ROW.fullmatch(line)
            if not match:
                raise ValueError('An HDFC transaction row could not be read safely; no transactions imported. This PDF layout needs review.')
            day,clock,description,credit,amount=match.groups()
            stamp=datetime.strptime(day+' '+clock,'%d/%m/%Y %H:%M')
            value=Decimal(amount.replace(',',''))
            rows.append({'Date':stamp.date().isoformat(),'Description':description,'Amount':float(value if credit else -value)})
    if not rows:
        raise ValueError('No supported HDFC credit-card transaction table was found in this PDF.')
    return rows
