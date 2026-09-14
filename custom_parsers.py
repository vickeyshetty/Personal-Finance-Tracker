"""Declarative parser definitions. No eval, imports, network or executable plugins."""
import csv
import hashlib
import hmac
import io
import json
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Request
from typing import Optional

FORMATS=('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d %b %Y','%d %b %y','%d/%m/%y','%d %b, %Y')
MANUAL_BUILTINS=[{'id':'builtin.csv','name':'CSV transaction columns','kind':'table'},
 {'id':'builtin.bank-excel','name':'HDFC / IDFC bank spreadsheets','kind':'table'},
 {'id':'builtin.card-excel','name':'HDFC card spreadsheets','kind':'table'},
 {'id':'builtin.sbi-pdf','name':'SBI Card PDF','kind':'pdf'},
 {'id':'builtin.indusind-pdf','name':'CRED / IndusInd PDF','kind':'pdf'}]

def init_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS custom_parsers (id TEXT PRIMARY KEY, definition TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, tested_hash TEXT NOT NULL)''')

def validate(d):
    if not isinstance(d,dict) or len(json.dumps(d))>12000: raise ValueError('Definition must be a JSON object under 12 KB.')
    if not re.fullmatch(r'custom\.[a-z0-9.-]{1,60}',str(d.get('id',''))): raise ValueError('ID must start with custom. and use lowercase letters, numbers, dots or hyphens.')
    if not isinstance(d.get('name'),str) or not 1<=len(d['name'])<=80: raise ValueError('Enter a name up to 80 characters.')
    if d.get('kind') not in ('email','pdf','table'): raise ValueError('Kind must be email, pdf or table.')
    if d.get('date_format') not in FORMATS: raise ValueError('Choose a supported date format.')
    if d.get('amount_mode') not in ('debit','credit','signed'): raise ValueError('Amount mode must be debit, credit or signed.')
    if d['kind']=='email':
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',str(d.get('sender',''))): raise ValueError('Email parsers require an exact sender.')
        if d.get('account_type') not in ('bank','credit_card') or not re.fullmatch('[a-z0-9-]{1,40}',str(d.get('issuer',''))): raise ValueError('Specify issuer and bank or credit_card account type.')
    if d['kind'] in ('email','pdf'):
        if not isinstance(d.get('contains'),str) or not 3<=len(d['contains'])<=200: raise ValueError('Use a distinctive literal marker of 3–200 characters.')
        if not isinstance(d.get('pattern'),str) or not 1<=len(d['pattern'])<=4000: raise ValueError('Provide an extraction pattern up to 4,000 characters.')
        import regex
        try: pattern=regex.compile(d['pattern'],regex.I|regex.M)
        except regex.error: raise ValueError('Invalid extraction pattern.') from None
        required={'date','amount'}|({'last4'} if d['kind']=='email' else {'description'})
        if not required.issubset(pattern.groupindex): raise ValueError('Pattern needs named groups: '+', '.join(sorted(required)))
        if 'description' not in pattern.groupindex and not isinstance(d.get('description_fallback'),str): raise ValueError('Supply description or description_fallback.')
        if d.get('description_fallback') and len(d['description_fallback'])>300: raise ValueError('Fallback description is too long.')
    else:
        columns=d.get('columns',{})
        if not isinstance(columns,dict) or any(not isinstance(columns.get(k),str) or not 1<=len(columns[k])<=100 for k in ('date','description','amount')): raise ValueError('Map date, description and amount to exact column headers.')
    return d

def amount(value,mode):
    value=str(value).strip().replace(',','')
    value=re.sub(r'^(INR|Rs\.?|₹)\s*','',value,flags=re.I)
    if value.startswith('(') and value.endswith(')'): value='-'+value[1:-1]
    try: number=Decimal(value)
    except InvalidOperation: raise ValueError('An amount could not be parsed.') from None
    if not number.is_finite() or number==0 or abs(number)>Decimal('1000000000000'): raise ValueError('Amount is zero, invalid or outside supported limits.')
    number=number.quantize(Decimal('.01'))
    if number==0: raise ValueError('Amount rounds to zero.')
    return float(-abs(number) if mode=='debit' else abs(number) if mode=='credit' else number)

def record(d,row):
    try: day=datetime.strptime(str(row['date']).strip(),d['date_format']).date().isoformat()
    except (ValueError,TypeError): raise ValueError('A date does not match date_format.') from None
    description=str(row.get('description') or d.get('description_fallback','')).strip()
    if not description or len(description)>1000: raise ValueError('Transaction description is missing or too long.')
    return {'Date':day,'Description':description,'Amount':amount(row['amount'],d['amount_mode'])}

def extract(d,sample):
    validate(d)
    if d['kind']=='table':
        matrix=list(csv.reader(io.StringIO(sample))) if isinstance(sample,str) else sample
        mapping={k:v.strip().lower() for k,v in d['columns'].items()}
        header=None;start=0
        for index,row in enumerate(matrix[:100]):
            normalized=[str(x).strip().lower() for x in row]
            if all(v in normalized for v in mapping.values()): header={k:normalized.index(v) for k,v in mapping.items()};start=index+1;break
        if header is None: raise ValueError('Mapped column headers were not found.')
        results=[]
        for row in matrix[start:]:
            if not any(str(v).strip() for v in row): continue
            if max(header.values())>=len(row): raise ValueError('Incomplete row; nothing imported. Refine the parser or input.')
            results.append(record(d,{k:row[i] for k,i in header.items()}))
    else:
        if not isinstance(sample,str) or len(sample)>500000: raise ValueError('Text must be under 500,000 characters.')
        if d['contains'].lower() not in sample.lower(): raise ValueError('Identification marker not found.')
        import regex
        try:
            matches=[]
            for m in regex.finditer(d['pattern'],sample,flags=regex.I|regex.M,timeout=.15):
                matches.append(m.groupdict())
                if len(matches)>5000: raise ValueError('Too many matches; refine the pattern.')
        except TimeoutError: raise ValueError('Pattern timed out. Simplify it before saving.') from None
        if d['kind']=='email':
            matches=list({json.dumps(m,sort_keys=True):m for m in matches}.values())
            if len(matches)!=1: raise ValueError('An email must contain exactly one distinct transaction.')
        results=[record(d,m) for m in matches]
        if d['kind']=='email' and results:
            suffix=matches[0]['last4']
            if not re.fullmatch(r'\d{4}',suffix): raise ValueError('last4 must contain exactly four digits.')
            r=results[0]
            return dict(date=r['Date'],description=r['Description'],amount=r['Amount'],time='00:00:00',kind='expense' if r['Amount']<0 else 'credit',account_last4=suffix,issuer=d['issuer'],account_type=d['account_type'],parser_id=d['id'],parser_version='custom-1',provisional=True,posted=False,currency='INR',note='Custom parser output. Time is not extracted; verify the account, date, amount and description against the original.')
    if not results: raise ValueError('No transactions matched.')
    return results

def enabled(ledger):
    return [json.loads(r['definition']) for r in ledger.rows('SELECT definition FROM custom_parsers WHERE enabled=1 ORDER BY id')]

def email(ledger,sender,subject,text):
    candidates=[d for d in enabled(ledger) if d['kind']=='email' and d['sender'].lower()==sender.lower() and d['contains'].lower() in text.lower()]
    if not candidates: return None
    if len(candidates)>1: raise ValueError('Multiple custom email parsers match; disable or narrow one.')
    return extract(candidates[0],text)

def statement(ledger,contents,extension,password=None):
    definitions=[d for d in enabled(ledger) if d['kind']==('pdf' if extension=='.pdf' else 'table')]
    if not definitions: return None
    if extension=='.pdf':
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contents),password=password) as doc: sample='\n'.join(p.extract_text() or '' for p in doc.pages)
        candidates=[d for d in definitions if d['contains'].lower() in sample.lower()]
    else:
        sample=list(csv.reader(io.StringIO(contents.decode('utf-8-sig')))) if extension=='.csv' else ledger.xls_matrix(contents) if extension=='.xls' else ledger.xlsx_matrix(contents)
        candidates=[d for d in definitions if any(all(v.strip().lower() in [str(x).strip().lower() for x in row] for v in d['columns'].values()) for row in sample[:100])]
    if not candidates: return None
    if len(candidates)>1: raise ValueError('Multiple custom statement parsers match; disable or narrow one.')
    return extract(candidates[0],sample)

def digest(d): return hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()

def bind(ledger):
    router=APIRouter(prefix='/api/developer')
    @router.get('/parsers')
    def catalog():
        import parsers
        return {'builtins':[dict(p,kind='email') for p in parsers.catalog()]+MANUAL_BUILTINS,'custom':[dict(r,definition=json.loads(r['definition'])) for r in ledger.rows('SELECT * FROM custom_parsers ORDER BY id')]}

    @router.post('/test')
    async def test(definition:str=Form(...),sample_text:str=Form(''),file:Optional[UploadFile]=File(None),password_account_id:Optional[int]=Form(None)):
        try:
            d=validate(json.loads(definition));sample=sample_text
            if file:
                content=await file.read(10*1024*1024+1)
                if len(content)>10*1024*1024: raise ValueError('Test files must be under 10 MB.')
                ext='.'+(file.filename or '').rsplit('.',1)[-1].lower()
                if d['kind']=='pdf' and ext=='.pdf':
                    import pdfplumber
                    import credential_store
                    with ledger.conn() as c: key=ledger.credential_key(c,password_account_id) if password_account_id else None
                    password=credential_store.read(key) if key else None
                    with pdfplumber.open(io.BytesIO(content),password=password) as doc: sample='\n'.join(p.extract_text() or '' for p in doc.pages)
                elif d['kind']=='table' and ext in ('.xls','.xlsx'):
                    sample=ledger.xls_matrix(content) if ext=='.xls' else ledger.xlsx_matrix(content)
                elif ext in ('.txt','.csv'): sample=content.decode('utf-8-sig')
                else: raise ValueError('Choose a matching PDF, spreadsheet, CSV or text test file.')
            output=extract(d,sample)
            payload=digest(d)+':'+str(int(time.time())+1800)
            token=payload+':'+hmac.new(ledger.LOCAL_TOKEN.encode(),payload.encode(),hashlib.sha256).hexdigest()
            return {'result':output,'test_token':token,'note':'Preview only. No transactions or sample content saved. Matching rows are not proof of statement completeness.'}
        except (ValueError,KeyError,TypeError): raise HTTPException(400,'Parser test failed. Check JSON, named groups, date/amount format, marker and sample rows.') from None
        except HTTPException: raise
        except Exception: raise HTTPException(400,'Could not test this file. Check its format/password and installed dependencies.') from None

    @router.post('/parsers')
    async def save(request:Request):
        try:
            data=await request.json();d=validate(data['definition']);token=data['test_token'];sha,expires,signature=token.split(':');payload=sha+':'+expires
            if sha!=digest(d) or int(expires)<time.time() or not hmac.compare_digest(signature,hmac.new(ledger.LOCAL_TOKEN.encode(),payload.encode(),hashlib.sha256).hexdigest()): raise ValueError()
        except Exception: raise HTTPException(400,'Test the current definition successfully before saving. Tests expire after 30 minutes or app restart.') from None
        with ledger.conn() as c:
            if c.execute('SELECT count(*) FROM custom_parsers').fetchone()[0]>=30 and not c.execute('SELECT 1 FROM custom_parsers WHERE id=?',(d['id'],)).fetchone(): raise HTTPException(400,'Maximum 30 custom parsers.')
            c.execute('INSERT INTO custom_parsers(id,definition,enabled,tested_hash) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET definition=excluded.definition,enabled=excluded.enabled,tested_hash=excluded.tested_hash',(d['id'],json.dumps(d),int(bool(data.get('enabled'))),sha))
        return {'ok':True}

    @router.post('/parsers/{parser_id}/toggle')
    def toggle(parser_id:str):
        with ledger.conn() as c: c.execute('UPDATE custom_parsers SET enabled=1-enabled WHERE id=?',(parser_id,))
        return {'ok':True}
    @router.delete('/parsers/{parser_id}')
    def remove(parser_id:str):
        with ledger.conn() as c: c.execute('DELETE FROM custom_parsers WHERE id=?',(parser_id,))
        return {'ok':True}
    return router
