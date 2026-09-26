"""Bank-reported balance snapshots, never ledger transactions."""
import re
from datetime import datetime, date
from decimal import Decimal

def init_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS balance_snapshots (
      id INTEGER PRIMARY KEY, mailbox TEXT NOT NULL, message_id TEXT NOT NULL,
      issuer TEXT NOT NULL, last4 TEXT NOT NULL, as_of TEXT NOT NULL,
      amount REAL NOT NULL, received TEXT NOT NULL, UNIQUE(mailbox,message_id))''')

def parse(sender,text):
    if sender.lower()!='alerts@hdfcbank.bank.in':return None
    pattern=r'available balance in your account ending [Xx*]*(\d{4}) is Rs\.?\s*(?:INR\s*)?(-?[\d,]+\.\d{2}) as of (\d{2}-[A-Za-z]{3}-\d{2})\.'
    matches={m.groups() for m in re.finditer(pattern,' '.join(text.split()),re.I)}
    if len(matches)!=1:return None
    suffix,amount,day=next(iter(matches))
    try:
        day=datetime.strptime(day,'%d-%b-%y').date().isoformat()
        value=Decimal(amount.replace(',',''))
        if not value.is_finite():return None
        return dict(issuer='hdfc',last4=suffix,as_of=day,amount=float(value))
    except (ValueError,ArithmeticError):return None

def capture(c,mailbox,message_id,received,sender,text):
    result=parse(sender,text)
    if not result:return False
    c.execute('INSERT OR IGNORE INTO balance_snapshots(mailbox,message_id,issuer,last4,as_of,amount,received) VALUES(?,?,?,?,?,?,?)',
              (mailbox,message_id,result['issuer'],result['last4'],result['as_of'],result['amount'],received))
    return True

def overview(c,today=None):
    today=today or date.today()
    accounts=[dict(r) for r in c.execute("SELECT id,name FROM accounts WHERE type='bank' AND archived=0 ORDER BY name")]
    snapshots=[dict(r) for r in c.execute('SELECT * FROM balance_snapshots ORDER BY as_of DESC,received DESC,id DESC')]
    links={(r['issuer'],r['last4']):r['account_id'] for r in c.execute("SELECT * FROM email_account_links WHERE account_type='bank'")}
    linked_ids={a['id'] for a in accounts}
    unlinked=[];seen=set()
    for s in snapshots:
        key=(s['issuer'],s['last4'])
        if links.get(key) not in linked_ids and key not in seen:
            unlinked.append(s);seen.add(key)
    for account in accounts:
        relevant=[s for s in snapshots if links.get((s['issuer'],s['last4']))==account['id']]
        account['snapshot']=None
        if not relevant:continue
        latest=relevant[0];day=latest['as_of']
        conflict=len({s['amount'] for s in relevant if s['as_of']==day})>1
        movement=c.execute("SELECT COALESCE(sum(amount),0),count(*) FROM transactions WHERE account_id=? AND status IN ('active','excluded') AND date>? AND date<=?",(account['id'],day,today.isoformat())).fetchone()
        same=c.execute("SELECT count(*) FROM transactions WHERE account_id=? AND status IN ('active','excluded') AND date=?",(account['id'],day)).fetchone()[0]
        review=c.execute("SELECT count(*) FROM transactions WHERE account_id=? AND status='review' AND date>=? AND date<=?",(account['id'],day,today.isoformat())).fetchone()[0]
        age=(today-date.fromisoformat(day)).days
        account['snapshot']={**latest,'estimated':None if conflict or age<0 else round(latest['amount']+movement[0],2),'movement':round(movement[0],2),'transaction_count':movement[1],'same_day_count':same,'review_count':review,'age_days':age,'conflict':conflict,'stale':age>=7}
    return {'accounts':accounts,'unlinked':unlinked}
