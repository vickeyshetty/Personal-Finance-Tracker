"""One reporting contract for calendar months and confirmed salary cycles."""
from calendar import monthrange
from collections import defaultdict
from datetime import date
from fastapi import APIRouter, HTTPException
import salary_cycles


def summarize(ledger, start, end, salaries=None, entries=None):
    entries = ledger.tx_rows('t.date>=? AND t.date<=?', (start, end)) if entries is None else [t for t in entries if start<=t['date']<=end]
    active = [t for t in entries if t['status'] == 'active']
    if salaries is None:
        salaries = [t for t in active if salary_cycles.eligible(t)]
    salary = round(sum(t['amount'] for t in salaries), 2) if salaries else None
    eligible = [t for t in active if t['kind'] not in ('transfer', 'repayment')
                and (t['amount'] < 0 or t['kind'] == 'refund')]
    investments = [t for t in eligible if t['category'] == 'Investments']
    spending = [t for t in eligible if t['category'] != 'Investments']
    groups = defaultdict(lambda: dict(gross=0, refunds=0, count=0))
    merchants = defaultdict(float)
    for t in spending:
        g = groups[t['category']]
        if t['amount'] < 0:
            g['gross'] -= t['amount']; g['count'] += 1
            merchants[t['description']] -= t['amount']
        else:
            g['refunds'] += t['amount']
    categories = sorted([dict(category=k, **{n:round(v, 2) for n,v in g.items()},
                              net=round(g['gross']-g['refunds'], 2)) for k,g in groups.items()],
                        key=lambda g:g['gross'], reverse=True)
    gross = round(sum(g['gross'] for g in categories), 2)
    refunds = round(sum(g['refunds'] for g in categories), 2)
    invested = round(-sum(t['amount'] for t in investments), 2)
    bank = [t for t in entries if t['account_type']=='bank' and t['kind']!='transfer'
            and (t['status']=='active' or (t['status']=='excluded' and t['kind']=='repayment'))]
    inflows = {'Salary / income':0, 'Refunds':0, 'Other credits':0}
    outflows = defaultdict(float)
    for t in bank:
        if t['amount'] > 0:
            key = 'Salary / income' if t['kind']=='income' else 'Refunds' if t['kind']=='refund' else 'Other credits'
            inflows[key] += t['amount']
        elif t['amount'] < 0:
            outflows['Card repayments' if t['kind']=='repayment' else t['category']] -= t['amount']
    incoming, outgoing = round(sum(inflows.values()),2), round(sum(outflows.values()),2)
    return dict(start=start,end=end,salary=salary,salary_entries=salaries,gross=gross,refunds=refunds,
                spent=round(gross-refunds,2),investments=invested,
                remaining=None if salary is None else round(salary-gross+refunds-invested,2),
                categories=categories,transactions=spending,investment_entries=investments,
                merchants=[dict(name=k,amount=round(v,2)) for k,v in sorted(merchants.items(),key=lambda p:p[1],reverse=True)[:5]],
                food=next((g for g in categories if g['category']=='Online food order'),dict(net=0,count=0,refunds=0)),
                review_count=sum(t['status']=='review' for t in entries),
                cash_flow=dict(incoming=incoming,outgoing=outgoing,net=round(incoming-outgoing,2),count=len(bank),
                               inflows={k:round(v,2) for k,v in inflows.items()},
                               outflows=[dict(category=k,amount=round(v,2)) for k,v in sorted(outflows.items(),key=lambda p:p[1],reverse=True)]))


def report(ledger, month='', cycle_id=None):
    # One request-local snapshot: shared by summary, chart and recurring patterns.
    # Never cache financial rows between requests; edits must appear immediately.
    entries = ledger.tx_rows()
    if cycle_id is not None:
        catalog = salary_cycles.catalog(ledger,entries)
        cycle = salary_cycles.report(ledger,cycle_id,catalog,entries)
        result = summarize(ledger,cycle['start'],cycle['end'],cycle['salary_entries'],entries)
        result.update(mode='salary',cycle_id=cycle_id,open=cycle['open'],estimated=cycle['estimated'])
        all_valid = [c for c in catalog['cycles'] if c['valid']]
        valid = all_valid[-6:]
        if not any(str(c['id'])==str(cycle_id) for c in valid):
            valid = [c for c in all_valid if str(c['id'])==str(cycle_id)]+valid
        result['trend'] = [dict(key=c['id'],start=c['start'],spent=salary_cycles.report(ledger,c['id'],catalog,entries)['spent']) for c in valid]
    else:
        try:
            start = date.fromisoformat(month+'-01')
            if start < date(2000,1,1) or start > date.today():
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400,'Choose a month from January 2000 through the current month.')
        end = min(date(start.year,start.month,monthrange(start.year,start.month)[1]),date.today())
        result = summarize(ledger,start.isoformat(),end.isoformat(),entries=entries)
        result.update(mode='month',month=month,open=end==date.today())
        result['trend'] = []
        today=date.today()
        indices=list(range(today.year*12+today.month-6,today.year*12+today.month))
        selected_index=start.year*12+start.month-1
        if selected_index not in indices:indices.insert(0,selected_index)
        for index in indices:
            first=date(index//12,index%12+1,1)
            last=min(date(first.year,first.month,monthrange(first.year,first.month)[1]),date.today())
            result['trend'].append(dict(key=first.strftime('%Y-%m'),start=first.isoformat(),spent=summarize(ledger,first.isoformat(),last.isoformat(),entries=entries)['spent']))
    # Historical detection remains contextual, not a claim these charges occurred this period.
    result['recurring'] = ledger.detect_recurring([t for t in entries if t['status']=='active' and t['amount']<0
        and t['kind'] not in ('transfer','repayment') and ledger.month_start(-5).isoformat()<=t['date']<=date.today().isoformat()])
    return result


def bind(ledger):
    router=APIRouter()
    @router.get('/api/period-report')
    def get_report(month:str='',cycle_id:str|None=None):
        return report(ledger,month,cycle_id)
    return router
