"""Confirmed salary boundaries and budgeting reports, separate from bank balances."""
from datetime import date,timedelta
from calendar import monthrange
from collections import defaultdict
from fastapi import APIRouter,HTTPException,Request

def init_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS salary_cycles (id INTEGER PRIMARY KEY, start TEXT NOT NULL UNIQUE, salary_id INTEGER UNIQUE)')

def eligible(t):
    return t['status']=='active' and t['account_type']=='bank' and t['amount']>0 and t['category']=='Salary' and t['kind'] not in ('transfer','repayment','refund')

def catalog(ledger, entries=None):
    tx=ledger.tx_rows('t.date<=?',(date.today().isoformat(),)) if entries is None else [t for t in entries if t['date']<=date.today().isoformat()]
    candidates=[t for t in tx if eligible(t)]
    ids={t['id'] for t in candidates}
    cycles=[{**r,'valid':r['salary_id'] is None or r['salary_id'] in ids} for r in ledger.rows('SELECT * FROM salary_cycles ORDER BY start')]
    # A confirmed starting point enables monthly reporting. Derived boundaries
    # are reporting-only: never create transactions or duplicate salary credits.
    confirmed=[c for c in cycles if c['valid']]
    if confirmed:
        linked={c['salary_id'] for c in confirmed if c['salary_id'] is not None}
        anchor=date.fromisoformat(confirmed[0]['start'])
        today=date.today()
        for index in range(anchor.year*12+anchor.month, today.year*12+today.month):
            year,month=divmod(index,12);month+=1
            prefix=f'{year:04d}-{month:02d}'
            if any(c['start'].startswith(prefix) for c in confirmed):continue
            previous=max((c for c in confirmed if c['start']<prefix),key=lambda c:c['start'])
            base=date.fromisoformat(previous['start'])
            last=monthrange(year,month)[1]
            day=last if base.day==monthrange(base.year,base.month)[1] else min(base.day,last)
            payday=min((t for t in candidates if t['date'].startswith(prefix) and t['id'] not in linked),key=lambda t:(t['date'],t['id']),default=None)
            start=payday['date'] if payday else date(year,month,day).isoformat()
            if start>today.isoformat():continue
            cycles.append(dict(id='auto-'+prefix,start=start,salary_id=payday['id'] if payday else None,
                               valid=True,automatic=True,estimated=payday is None))
    cycles.sort(key=lambda c:c['start'])
    return {'candidates':candidates,'cycles':cycles}

def report(ledger,cycle_id,catalog_data=None,entries=None):
    catalog_data=catalog(ledger,entries) if catalog_data is None else catalog_data
    cycles=[c for c in catalog_data['cycles'] if c['valid']]
    cycle=next((c for c in cycles if str(c['id'])==str(cycle_id)),None)
    if not cycle:raise HTTPException(400,'This cycle has no valid salary link. Update its setup first.')
    next_cycle=next((c for c in cycles if c['start']>cycle['start']),None)
    end=(date.fromisoformat(next_cycle['start'])-timedelta(days=1)).isoformat() if next_cycle else date.today().isoformat()
    period_entries=ledger.tx_rows('t.date>=? AND t.date<=?',(cycle['start'],end)) if entries is None else [t for t in entries if cycle['start']<=t['date']<=end]
    tx=[t for t in period_entries if t['status']=='active']
    anchors={c['salary_id'] for c in cycles if c['salary_id'] is not None}
    salaries=[t for t in catalog_data['candidates'] if t['id']==cycle['salary_id'] or (cycle['start']<=t['date']<=end and t['id'] not in anchors)]
    salary=round(sum(t['amount'] for t in salaries),2) if salaries else None
    spending=[];investments=[];groups=defaultdict(lambda:{'gross':0,'refunds':0})
    for t in tx:
        if t['kind'] in ('transfer','repayment'):continue
        if t['amount']>=0 and t['kind']!='refund':continue
        if t['category']=='Investments':investments.append(t);continue
        spending.append(t)
        groups[t['category']]['gross' if t['amount']<0 else 'refunds']+=abs(t['amount'])
    gross=round(-sum(t['amount'] for t in spending if t['amount']<0),2)
    refunds=round(sum(t['amount'] for t in spending if t['amount']>0),2)
    net=round(gross-refunds,2);invested=round(-sum(t['amount'] for t in investments),2)
    categories=[dict(category=k,gross=round(v['gross'],2),refunds=round(v['refunds'],2),net=round(v['gross']-v['refunds'],2)) for k,v in groups.items()]
    return dict(id=cycle_id,start=cycle['start'],end=end,open=next_cycle is None,estimated=cycle.get('estimated',False),salary=salary,salary_entries=salaries,gross=gross,refunds=refunds,spent=net,investments=invested,remaining=None if salary is None else round(salary-net-invested,2),categories=sorted(categories,key=lambda g:g['gross'],reverse=True),transactions=spending+investments,review_count=sum(t['status']=='review' for t in period_entries))

def bind(ledger):
    router=APIRouter(prefix='/api/salary-cycles')
    @router.get('')
    def listing():return catalog(ledger)
    @router.get('/{cycle_id}')
    def details(cycle_id:str):return report(ledger,cycle_id)
    @router.post('')
    async def save(request:Request):
        try:
            data=await request.json();start=date.fromisoformat(data['start'])
            salary_id=int(data['salary_id']) if data.get('salary_id') else None
            cycle_id=int(data['id']) if data.get('id') else None
            if start>date.today() or start.year<2000:raise ValueError()
        except (ValueError,KeyError,TypeError):raise HTTPException(400,'Choose a valid start date, not in the future.')
        if salary_id is not None and not any(t['id']==salary_id for t in catalog(ledger)['candidates']):raise HTTPException(400,'Choose an active bank credit categorized as Salary.')
        with ledger.conn() as c:
            if cycle_id and not c.execute('SELECT 1 FROM salary_cycles WHERE id=?',(cycle_id,)).fetchone():raise HTTPException(404,'Cycle not found.')
            if c.execute('SELECT 1 FROM salary_cycles WHERE (start=? OR (? IS NOT NULL AND salary_id=?)) AND id!=?',(start.isoformat(),salary_id,salary_id,cycle_id or -1)).fetchone():raise HTTPException(400,'This start date or salary entry already has a cycle. Edit that cycle instead.')
            if cycle_id:c.execute('UPDATE salary_cycles SET start=?,salary_id=? WHERE id=?',(start.isoformat(),salary_id,cycle_id))
            else:cycle_id=c.execute('INSERT INTO salary_cycles(start,salary_id) VALUES(?,?)',(start.isoformat(),salary_id)).lastrowid
        return {'id':cycle_id}
    @router.delete('/{cycle_id}')
    def remove(cycle_id:int):
        with ledger.conn() as c:c.execute('DELETE FROM salary_cycles WHERE id=?',(cycle_id,))
        return {'ok':True}
    return router
