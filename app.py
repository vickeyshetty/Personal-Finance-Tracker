from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import zipfile
import math
import json
import uuid
import secrets
import credential_store
import gmail_ingestion
import sys
from contextlib import contextmanager
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
DB = ROOT / "finance.db"
app = FastAPI(title="Personal Finance Tracker")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
LOCAL_TOKEN = secrets.token_urlsafe(32)


@app.middleware('http')
async def local_browser_guard(request: Request, call_next):
    origin = request.headers.get('origin')
    if (request.headers.get('sec-fetch-site') == 'cross-site' or
            (origin and origin != str(request.base_url).rstrip('/'))):
        return JSONResponse({'detail': 'Cross-site access is not allowed.'}, status_code=403)
    if '/statement-password' in request.url.path or request.url.path.startswith('/api/gmail/'):
        if not secrets.compare_digest(request.headers.get('x-ledger-token', ''), LOCAL_TOKEN):
            return JSONResponse({'detail': 'Refresh Ledger before managing passwords.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(credential_store.VaultUnavailable)
async def vault_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=503)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, type TEXT NOT NULL CHECK(type IN ('bank','credit_card')), currency TEXT NOT NULL DEFAULT 'INR');
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, parent_category TEXT);
CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, date TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL, account_id INTEGER NOT NULL, category_id INTEGER, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','deleted','excluded','review')), is_recurring INTEGER DEFAULT 0, source_file TEXT, raw_hash TEXT NOT NULL, deleted_at TEXT, edited_at TEXT, split_group TEXT, FOREIGN KEY(account_id) REFERENCES accounts(id), FOREIGN KEY(category_id) REFERENCES categories(id));
CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY, merchant_pattern TEXT UNIQUE NOT NULL, category_id INTEGER NOT NULL, FOREIGN KEY(category_id) REFERENCES categories(id));
CREATE INDEX IF NOT EXISTS ix_tx_hash ON transactions(raw_hash);
"""
DEFAULT_CATEGORIES = ["Uncategorized", "Groceries", "Dining", "Transport", "Shopping", "Bills & Utilities", "Health", "Entertainment", "Travel", "Salary", "Income", "Transfers", "Credit Card Payment", "Refund / Cashback"]

@contextmanager
def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:
            yield c
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        gmail_ingestion.init_schema(c)
        c.execute('CREATE TABLE IF NOT EXISTS statement_credentials (account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, credential_key TEXT UNIQUE NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS card_identities (issuer TEXT NOT NULL, last4 TEXT NOT NULL, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, PRIMARY KEY(issuer,last4))')
        for name in DEFAULT_CATEGORIES:
            c.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
        c.execute("INSERT OR IGNORE INTO categories(name) VALUES('Online food order')")
        c.execute("INSERT OR IGNORE INTO categories(name) VALUES('Quick commerce')")
        old_people=c.execute("SELECT id FROM categories WHERE name='Money to/from people'").fetchone()
        people=c.execute("SELECT id FROM categories WHERE name='People'").fetchone()
        if old_people and not people:
            c.execute("UPDATE categories SET name='People' WHERE id=?",(old_people['id'],))
        else:
            c.execute("INSERT OR IGNORE INTO categories(name) VALUES('People')")
        if not c.execute('SELECT 1 FROM accounts').fetchone():
            c.execute("INSERT INTO accounts(name,type) VALUES('Primary bank','bank')")
        c.executescript("""CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS imports (id INTEGER PRIMARY KEY, filename TEXT NOT NULL, account_id INTEGER, created_at TEXT NOT NULL, undone INTEGER DEFAULT 0, legacy INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, transaction_id INTEGER, before_json TEXT, changed_at TEXT);
            CREATE TABLE IF NOT EXISTS account_aliases (name TEXT PRIMARY KEY, account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE);""")
        additions = {'import_id':'INTEGER', 'source_hash':'TEXT', 'previous_status':'TEXT', 'kind':"TEXT DEFAULT 'other'", 'transfer_link':'TEXT'}
        columns = {r['name'] for r in c.execute('PRAGMA table_info(transactions)')}
        for name, definition in additions.items():
            if name not in columns: c.execute(f'ALTER TABLE transactions ADD COLUMN {name} {definition}')
        if 'archived' not in {r['name'] for r in c.execute('PRAGMA table_info(accounts)')}:
            c.execute('ALTER TABLE accounts ADD COLUMN archived INTEGER DEFAULT 0')
        if not c.execute("SELECT 1 FROM migrations WHERE name='swiggy-category-v1'").fetchone():
            category=c.execute("SELECT id FROM categories WHERE name='Online food order'").fetchone()[0]
            for t in c.execute("SELECT id FROM transactions WHERE lower(description) LIKE '%swiggy%'").fetchall():
                audit_transaction(c,t['id'])
            c.execute("UPDATE transactions SET category_id=? WHERE lower(description) LIKE '%swiggy%'",(category,))
            c.execute("UPDATE rules SET category_id=? WHERE lower(merchant_pattern) LIKE '%swiggy%'",(category,))
            c.execute("INSERT INTO rules(merchant_pattern,category_id) VALUES('swiggy',?) ON CONFLICT(merchant_pattern) DO UPDATE SET category_id=excluded.category_id",(category,))
            c.execute("INSERT INTO migrations VALUES('swiggy-category-v1')")
        if not c.execute("SELECT 1 FROM migrations WHERE name='quick-commerce-v1'").fetchone():
            category=c.execute("SELECT id FROM categories WHERE name='Quick commerce'").fetchone()[0]
            for t in c.execute("SELECT id FROM transactions WHERE lower(description) LIKE '%instamart%' OR lower(description) LIKE '%zepto%'").fetchall():
                audit_transaction(c,t['id'])
            c.execute("UPDATE transactions SET category_id=? WHERE lower(description) LIKE '%instamart%' OR lower(description) LIKE '%zepto%'",(category,))
            c.execute("UPDATE rules SET category_id=? WHERE lower(merchant_pattern) LIKE '%instamart%' OR lower(merchant_pattern) LIKE '%zepto%'",(category,))
            for pattern in ('instamart','swiggyinstamart','zepto'):
                c.execute('INSERT INTO rules(merchant_pattern,category_id) VALUES(?,?) ON CONFLICT(merchant_pattern) DO UPDATE SET category_id=excluded.category_id',(pattern,category))
            c.execute("INSERT INTO migrations VALUES('quick-commerce-v1')")
        if not c.execute("SELECT 1 FROM migrations WHERE name='card-credit-labels-v2'").fetchone():
            for t in c.execute("SELECT * FROM transactions WHERE kind='credit' AND edited_at IS NULL AND amount>0").fetchall():
                kind=infer_kind(t['description'],t['amount'],'credit_card')
                if kind in ('refund','repayment'):
                    c.execute('UPDATE transactions SET kind=? WHERE id=?',(kind,t['id']))
            c.execute("INSERT INTO migrations VALUES('card-credit-labels-v2')")
        if c.execute("SELECT 1 FROM migrations WHERE name='reliability-v1'").fetchone(): return
        for t in c.execute('SELECT t.*,a.type,c.name category FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id').fetchall():
            kind = infer_kind(t['description'], t['amount'], t['type'], t['category'])
            previous = 'excluded' if kind in ('transfer','repayment') else 'active'
            c.execute('UPDATE transactions SET kind=?, source_hash=raw_hash, previous_status=? WHERE id=?', (kind,previous,t['id']))
        # Historical uploads have no batch IDs. Group them visibly by file and account.
        for group in c.execute('SELECT source_file,account_id FROM transactions GROUP BY source_file,account_id').fetchall():
            batch = c.execute('INSERT INTO imports(filename,account_id,created_at,legacy) VALUES(?,?,?,1)', (group['source_file'] or 'Historical transactions',group['account_id'],datetime.now().isoformat())).lastrowid
            c.execute('UPDATE transactions SET import_id=? WHERE source_file IS ? AND account_id=?',(batch,group['source_file'],group['account_id']))
        c.execute("INSERT INTO migrations VALUES('reliability-v1')")
        return

@app.on_event("startup")
def startup():
    if DB.exists():
        folder=ROOT/'backups'; folder.mkdir(exist_ok=True)
        target=folder/('daily-'+date.today().isoformat()+'.db')
        if not target.exists():
            with sqlite3.connect(DB) as source, sqlite3.connect(target) as destination: source.backup(destination)
    init_db()

def rows(query, args=()):
    with conn() as c: return [dict(r) for r in c.execute(query, args).fetchall()]

def tx_rows(where="1=1", args=()):
    return rows(f"""SELECT t.*, a.name account_name, a.type account_type, COALESCE(c.name,'Uncategorized') category
        FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id
        WHERE {where} ORDER BY t.date DESC, t.id DESC""", args)

def raw_hash(day, amount, description, account):
    value = f"{day}|{float(amount):.2f}|{description.strip().lower()}|{account.strip().lower()}"
    return hashlib.sha256(value.encode()).hexdigest()

def is_credit_card_statement(filename):
    name = filename.lower()
    return "billedstatement" in name or "transactionstatement" in name or "sbi card statement" in name

def ensure_credit_card_account(database, filename):
    matches = re.findall(r"_(\d{4})(?=_)", filename)
    if "sbi card statement" in filename.lower() and matches: name = f"SBI Card ending {matches[-1]}"
    elif matches and matches[-1] == "1783": name = "HDFC Bank Millennia Credit Card"
    elif matches: name = f"Credit Card ending {matches[-1]}"
    elif "transactionstatement" in filename.lower(): name = "CRED IndusInd Card"
    else: name = "Credit Card"
    return ensure_account(database,name,'credit_card')

def ensure_account(database, name, account_type="bank"):
    alias = database.execute('SELECT a.* FROM account_aliases x JOIN accounts a ON a.id=x.account_id WHERE x.name=?',(name,)).fetchone()
    if alias: return alias
    database.execute("INSERT OR IGNORE INTO accounts(name,type) VALUES(?, ?)", (name, account_type))
    return database.execute("SELECT * FROM accounts WHERE name=?", (name,)).fetchone()

def automatic_statement_account(database, filename, extension, contents, password=None):
    """Return the known account for a supported statement, else None for the user's fallback choice."""
    if extension == '.pdf':
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contents), password=password) as document:
            text = document.pages[0].extract_text() or ''
        if 'GSTIN of SBI Card' in text:
            return ensure_credit_card_account(database, filename if 'sbi card statement' in filename.lower() else 'SBI Card Statement')
        if 'IndusInd' in text or 'Payment Details for' in text:
            return ensure_account(database, 'CRED IndusInd Card', 'credit_card')
    if extension not in (".xls", ".xlsx", '.csv'):
        return None
    try:
        matrix = list(csv.reader(io.StringIO(contents.decode('utf-8-sig')))) if extension=='.csv' else (xls_matrix(contents) if extension == '.xls' else xlsx_matrix(contents))
        _, header = find_statement_header(matrix)
        columns = {str(value).strip().lower() for value in (header or [])}
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError):
        return None
    if {"date & time", "description", "amt", "debit / credit"}.issubset(columns):
        if 'billedstatement' in filename.lower(): return ensure_credit_card_account(database, filename)
        return ensure_account(database, "HDFC Bank Millennia Credit Card", "credit_card")
    if {"transaction date", "particulars", "debit", "credit"}.issubset(columns):
        return ensure_account(database, "IDFC Bank")
    if {"date", "narration", "withdrawal amt.", "deposit amt."}.issubset(columns):
        return ensure_account(database, "HDFC Bank")
    return None

def is_card_payment(description):
    text = description.lower()
    return "payment on cred" in text or "ib billpay dr-hdfc" in text or "credit card payment" in text or "cc payment" in text

def infer_kind(description, amount, account_type, category=None):
    if category == 'Transfers': return 'transfer'
    if category == 'Credit Card Payment': return 'repayment'
    if category == 'Refund / Cashback': return 'refund'
    if is_card_payment(description) or (account_type == 'credit_card' and amount > 0 and re.search(r'payment received|^bbps payment\b',description,re.I)): return 'repayment'
    if amount > 0 and re.search(r'refund|cashback|reversal|surcharge waiver', description, re.I): return 'refund'
    if amount > 0: return 'credit' if account_type == 'credit_card' else 'income'
    return 'expense'

def audit_transaction(c, tx_id):
    row = c.execute('SELECT * FROM transactions WHERE id=?',(tx_id,)).fetchone()
    if row: c.execute('INSERT INTO audit(transaction_id,before_json,changed_at) VALUES(?,?,?)',(tx_id,json.dumps(dict(row)),datetime.now().isoformat()))

def categorise(description, database=None):
    if database is None:
        rules = rows("SELECT r.merchant_pattern, c.id category_id FROM rules r JOIN categories c ON c.id=r.category_id ORDER BY length(r.merchant_pattern) DESC,r.id")
        uncategorized = rows("SELECT id FROM categories WHERE name='Uncategorized'")[0]["id"]
    else:
        rules = [dict(row) for row in database.execute("SELECT r.merchant_pattern, c.id category_id FROM rules r JOIN categories c ON c.id=r.category_id ORDER BY length(r.merchant_pattern) DESC,r.id")]
        uncategorized = database.execute("SELECT id FROM categories WHERE name='Uncategorized'").fetchone()["id"]
    for rule in rules:
        if rule["merchant_pattern"].lower() in description.lower(): return rule["category_id"]
    return uncategorized

class TransactionUpdate(BaseModel):
    date: str
    description: str
    amount: float
    category_id: Optional[int] = None
    account_id: int
    status: str = "active"
    create_rule: bool = False
    kind: Optional[str] = None

@app.get("/")
def index():
    html=(ROOT/'static'/'index.html').read_text(encoding='utf-8')
    # Match the script version to its contents so HTML changes cannot reuse old JS.
    version=hashlib.sha256((ROOT/'static'/'app.js').read_bytes()).hexdigest()[:12]
    html=re.sub(r'/static/app\.js(?:\?[^"\s]*)?', '/static/app.js?v='+version, html)
    html=html.replace('</head>', f'<meta name="ledger-token" content="{LOCAL_TOKEN}"></head>')
    gmail_version=hashlib.sha256((ROOT/'static'/'gmail.js').read_bytes()).hexdigest()[:12]
    html=html.replace('</body>',f'<script src="/static/gmail.js?v={gmail_version}"></script></body>')
    return HTMLResponse(html,headers={'Cache-Control':'no-store'})

@app.get("/api/bootstrap")
def bootstrap():
    return {"accounts": rows("SELECT * FROM accounts ORDER BY name"), "categories": rows("SELECT * FROM categories ORDER BY name"), "transactions": tx_rows("t.status IN ('active','excluded')"), "trash": tx_rows("t.status = 'deleted'"), "review": tx_rows("t.status = 'review'")}

@app.post("/api/accounts")
def create_account(name: str = Form(...), type: str = Form(...), currency: str = Form("INR")):
    if type not in ("bank", "credit_card"): raise HTTPException(400, "Account type must be bank or credit_card")
    if not name.strip(): raise HTTPException(400,'Enter an account name.')
    if currency.upper()!='INR': raise HTTPException(400,'Only INR accounts are currently supported.')
    with conn() as c:
        try: c.execute("INSERT INTO accounts(name,type,currency) VALUES(?,?,?)", (name.strip(), type, currency.upper()))
        except sqlite3.IntegrityError: raise HTTPException(400, "That account already exists")
    return {"ok": True}

@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int):
    with conn() as c:
        account = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not account: raise HTTPException(404, "Account not found")
        transaction_count = c.execute("SELECT count(*) FROM transactions WHERE account_id=?", (account_id,)).fetchone()[0]
        if transaction_count: raise HTTPException(400, "This account has transactions. Move or delete those transactions before removing the account.")
        credential = c.execute('SELECT credential_key FROM statement_credentials WHERE account_id=?', (account_id,)).fetchone()
        if credential: credential_store.remove(credential['credential_key'])
        c.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True}


def credential_key(c, account_id):
    if not c.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
        raise HTTPException(404, 'Account not found')
    record = c.execute('SELECT credential_key FROM statement_credentials WHERE account_id=?', (account_id,)).fetchone()
    return record['credential_key'] if record else None


@app.get('/api/accounts/{account_id}/statement-password')
def password_status(account_id: int):
    with conn() as c:
        key = credential_key(c, account_id)
    credential_store.backend()
    return {'saved': bool(key and credential_store.read(key) is not None)}


@app.put('/api/accounts/{account_id}/statement-password')
async def save_statement_password(account_id: int, request: Request):
    # Parse manually: validation responses must never echo a submitted secret.
    raw = await request.body()
    if len(raw) > 8192: raise HTTPException(400, 'Password request is too large.')
    try:
        value = json.loads(raw).get('password')
    except Exception:
        raise HTTPException(400, 'Enter a valid password.') from None
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise HTTPException(400, 'Enter a password between 1 and 1000 characters.')
    with conn() as c:
        key = credential_key(c, account_id)
        if not key:
            key = str(uuid.uuid4())
            c.execute('INSERT INTO statement_credentials VALUES (?,?)', (account_id, key))
        credential_store.save(key, value)
    return {'saved': True}


@app.delete('/api/accounts/{account_id}/statement-password')
def remove_statement_password(account_id: int):
    with conn() as c:
        key = credential_key(c, account_id)
        if key: credential_store.remove(key)
        c.execute('DELETE FROM statement_credentials WHERE account_id=?', (account_id,))
    return {'saved': False}


@app.post("/api/import")
async def import_csv(account_id: int = Form(...), file: UploadFile = File(...), preview: bool = Form(False), override: bool = Form(False), password_account_id: Optional[int] = Form(None)):
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in (".csv", ".xls", ".xlsx", ".pdf"): raise HTTPException(400, "Upload a CSV, Excel (.xls/.xlsx), or supported PDF statement.")
    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024: raise HTTPException(400, 'Statement must be smaller than 25 MB.')
    password = None
    if extension == '.pdf' and password_account_id is not None:
        with conn() as c:
            key = credential_key(c, password_account_id)
        password = credential_store.read(key) if key else None
        if password is None: raise HTTPException(400, 'No saved password for the selected PDF password account. Save one in Statement passwords first.')
    try:
        reader = read_statement(contents, extension, filename, password=password)
    except Exception as exc:
        from pdfminer.pdfdocument import PDFPasswordIncorrect
        if isinstance(exc, PDFPasswordIncorrect):
            raise HTTPException(400, 'PDF is locked or the saved password is incorrect. Save/update its statement password and select the PDF password account before retrying.') from None
        raise HTTPException(400, 'Could not read this statement. It may be password protected, damaged, or an unsupported layout. ' + (str(exc) if isinstance(exc, ValueError) else ''))
    if not reader: raise HTTPException(400, "The statement is empty or has no header row.")
    fields = {str(f).lower().strip(): f for f in reader[0]}
    def field(*names): return next((fields[n] for n in names if n in fields), None)
    dcol, xcol, acol = field("date", "transaction date", "txn date"), field("description", "narration", "merchant", "particulars"), field("amount", "transaction amount", "debit")
    if not all((dcol, xcol, acol)): raise HTTPException(400, "Use headers Date, Description, Amount (or Transaction Date/Narration).")
    created = review = skipped = 0
    with conn() as c:
        account = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not account: raise HTTPException(404, "Account not found")
        detected_account = automatic_statement_account(c, filename, extension, contents, password=password)
        if detected_account and not override:
            account = detected_account
        if account['archived']: raise HTTPException(400,'This account is archived. Unarchive it before importing.')
        batch = None if preview else c.execute('INSERT INTO imports(filename,account_id,created_at) VALUES(?,?,?)',(filename,account['id'],datetime.now().isoformat())).lastrowid
        parsed = []
        card_payment_category = c.execute("SELECT id FROM categories WHERE name='Credit Card Payment'").fetchone()["id"]
        for item in reader:
            try:
                day = parse_date(item[dcol]); description = str(item[xcol] or '').strip(); amount = parse_amount(item[acol])
                if not description: raise ValueError('Missing description')
            except (ValueError, TypeError, AttributeError): skipped += 1; continue
            h = raw_hash(day, amount, description, account["name"])
            duplicate = c.execute("SELECT 1 FROM transactions WHERE (raw_hash=? OR source_hash=?) AND status!='deleted'", (h,h)).fetchone() or any(r['hash']==h for r in parsed)
            kind = infer_kind(description,amount,account['type'])
            status = 'review' if duplicate else ('excluded' if kind in ('transfer','repayment') else 'active')
            category_id = card_payment_category if is_card_payment(description) else categorise(description, c)
            if kind == 'repayment': category_id = card_payment_category
            if kind == 'refund' and category_id == c.execute("SELECT id FROM categories WHERE name='Uncategorized'").fetchone()[0]: category_id = c.execute("SELECT id FROM categories WHERE name='Refund / Cashback'").fetchone()[0]
            parsed.append(dict(date=day,description=description,amount=amount,kind=kind,duplicate=bool(duplicate),hash=h))
            if not preview:
                c.execute("INSERT INTO transactions(date,description,amount,account_id,category_id,status,source_file,raw_hash,source_hash,import_id,kind,previous_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (day,description,amount,account['id'],category_id,status,filename,h,h,batch,kind,'excluded' if kind in ('transfer','repayment') else 'active'))
            review += bool(duplicate); created += not bool(duplicate)
        if not parsed: raise HTTPException(400,'No valid transactions found; nothing imported.')
        if preview: c.rollback()
    return {"created": created, "review": review, "skipped": skipped, "account": account["name"], 'detected': bool(detected_account), 'import_id':batch, 'rows':parsed, 'debits':round(-sum(r['amount'] for r in parsed if r['amount']<0),2), 'credits':round(sum(r['amount'] for r in parsed if r['amount']>0),2)}

def parse_date(value):
    if isinstance(value, (int, float)):
        # Excel's 1900-based serial dates (including the historic leap-year quirk).
        return (date(1899, 12, 30) + timedelta(days=value)).isoformat()
    value = value.strip().split(" / ")[0]
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%m/%d/%Y", "%d %b %Y", "%d %b %y", "%d-%b-%Y"):
        try: return datetime.strptime(value, f).date().isoformat()
        except ValueError: pass
    raise ValueError(value)
def parse_amount(value):
    text = str(value).strip()
    amount = float(re.sub(r"[^0-9.\-]", "", text.replace(',', '')))
    if not math.isfinite(amount): raise ValueError('Invalid amount')
    if text.startswith('(') and text.endswith(')'): amount = -abs(amount)
    return round(amount,2)

def read_statement(contents: bytes, extension: str, filename: str = "", password=None):
    """Return normalised rows from CSV, supported bank/card Excel, or recognised card PDF."""
    if extension == ".csv":
        matrix = list(csv.reader(io.StringIO(contents.decode('utf-8-sig'))))
        return normalise_excel_statement(matrix)
    if extension == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contents), password=password) as document:
            first_page = document.pages[0].extract_text() or ''
        if 'GSTIN of SBI Card' in first_page:
            return sbi_card_pdf_rows(contents, password=password)
        return cred_indusind_pdf_rows(contents, password=password)
    try:
        matrix = xls_matrix(contents) if extension == ".xls" else xlsx_matrix(contents)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError) as exc:
        raise ValueError("This does not look like a readable Excel workbook.") from exc
    return normalise_excel_statement(matrix)

def cred_indusind_pdf_rows(contents: bytes, password=None):
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("PDF import needs pdfplumber. Run: python -m pip install -r requirements.txt") from exc
    transaction = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d+)\s+([\d,]+\.\d{2})\s+(CR|DR)\b")
    section = None; result=[]
    with pdfplumber.open(io.BytesIO(contents), password=password) as document:
        for page in document.pages:
            for line in (page.extract_text() or "").splitlines():
                if line.startswith("Payment Details for "): section = "payments"; continue
                if line.startswith("Purchases & Cash Transactions for "): section = "purchases"; continue
                match = transaction.search(line.strip())
                if not match or section is None: continue
                day, description, _, amount, direction = match.groups()
                value = abs(parse_amount(amount)) if direction == "CR" else -abs(parse_amount(amount))
                result.append({"Date": day, "Description": description, "Amount": value})
    if not result: raise ValueError("Could not find CRED/IndusInd card transactions in this PDF.")
    return result

def sbi_card_pdf_rows(contents: bytes, password=None):
    """Read SBI Card PDFs, whose dated transaction rows may be followed by dated fee lines."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("PDF import needs pdfplumber. Run: python -m pip install -r requirements.txt") from exc
    dated = re.compile(r"^(\d{2}\s+[A-Za-z]{3}\s+\d{2})\s+(.+?)\s+([\d,]+\.\d{2})\s+([CD])$")
    continuing = re.compile(r"^(.+?)\s+([\d,]+\.\d{2})\s+([CD])$")
    result = []
    with pdfplumber.open(io.BytesIO(contents), password=password) as document:
        for page in document.pages:
            in_transactions = False
            current_day = None
            for raw_line in (page.extract_text() or "").splitlines():
                line = raw_line.strip()
                if line.startswith("Date Transaction Details Amount") or line.startswith("TRANSACTIONS FOR "):
                    in_transactions = True
                    continue
                if not in_transactions:
                    continue
                if line.startswith("Transactions highlighted"):
                    in_transactions = False
                    current_day = None
                    continue
                match = dated.match(line)
                if match:
                    raw_day, description, amount, direction = match.groups()
                    current_day = parse_date(raw_day)
                else:
                    match = continuing.match(line)
                    if not match or not current_day:
                        continue
                    description, amount, direction = match.groups()
                value = abs(parse_amount(amount)) if direction == "C" else -abs(parse_amount(amount))
                result.append({"Date": current_day, "Description": description, "Amount": value})
    if not result:
        raise ValueError("Could not find SBI Card transactions in this PDF.")
    return result

def xls_matrix(contents: bytes):
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError("Legacy .xls import needs xlrd. Run: python -m pip install -r requirements.txt") from exc
    book = xlrd.open_workbook(file_contents=contents)
    sheet = book.sheet_by_index(0)
    return [sheet.row_values(index) for index in range(sheet.nrows)]

def normalise_excel_statement(matrix):
    if not matrix: return []
    header_index, header = find_statement_header(matrix)
    if header is None:
        raise ValueError("Could not find a supported transaction header in this workbook.")
    lookup = {str(value).strip().lower(): i for i, value in enumerate(header)}
    def value(row, name):
        index = lookup.get(name.lower())
        return row[index] if index is not None and index < len(row) else ""
    is_hdfc = "narration" in lookup and "withdrawal amt." in lookup
    is_idfc = "particulars" in lookup and "transaction date" in lookup
    is_credit_card = {"date & time", "description", "amt", "debit / credit"}.issubset(lookup)
    result=[]
    for row in matrix[header_index + 1:]:
        if not any(cell not in (None, "") for cell in row): continue
        if is_credit_card:
            day, description, amount, direction = value(row, "date & time"), value(row, "description"), value(row, "amt"), value(row, "debit / credit")
            if not day or not description or amount in (None, ""): continue
            try:
                parse_date(day)
                signed_amount = abs(parse_amount(amount)) if str(direction).strip().lower() == "cr" else -abs(parse_amount(amount))
            except (ValueError, TypeError, AttributeError):
                continue
            result.append({"Date": day, "Description": description, "Amount": signed_amount})
            continue
        if is_hdfc:
            day, description = value(row, "date"), value(row, "narration")
            debit, credit = value(row, "withdrawal amt."), value(row, "deposit amt.")
        elif is_idfc:
            day, description = value(row, "transaction date"), value(row, "particulars")
            debit, credit = value(row, "debit"), value(row, "credit")
        else:
            day, description, amount = value(row, "date") or value(row, "transaction date"), value(row, "description") or value(row, "narration") or value(row, "particulars"), value(row, "amount") or value(row, "transaction amount")
            if day and description and amount not in (None, ""):
                result.append({"Date": day, "Description": description, "Amount": amount})
            continue
        if not day or not description or str(day).startswith("*"): continue
        try:
            parse_date(day)
        except (ValueError, TypeError, AttributeError):
            continue
        debit_value = abs(parse_amount(debit)) if str(debit or '').strip() else 0
        credit_value = abs(parse_amount(credit)) if str(credit or '').strip() else 0
        if debit_value and credit_value: raise ValueError('A row has both debit and credit amounts; please check the statement.')
        result.append({"Date": day, "Description": description, "Amount": round(credit_value-debit_value,2)})
    return result

def find_statement_header(matrix):
    for index, row in enumerate(matrix):
        lowered = {str(cell).strip().lower() for cell in row if cell not in (None, "")}
        if {"date", "narration", "withdrawal amt.", "deposit amt."}.issubset(lowered): return index, row
        if {"transaction date", "particulars", "debit", "credit"}.issubset(lowered): return index, row
        if {"date & time", "description", "amt", "debit / credit"}.issubset(lowered): return index, row
        if {"date", "description", "amount"}.issubset(lowered): return index, row
    return None, None

def xlsx_matrix(contents: bytes):
    """Small dependency-free reader for values from the first worksheet."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(contents)) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in item.iter(ns + "t")) for item in root.findall(ns + "si")]
        sheets = sorted(n for n in book.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets: return []
        root = ET.fromstring(book.read(sheets[0])); output=[]
        for row in root.iter(ns + "row"):
            values={}
            for cell in row.findall(ns + "c"):
                ref=cell.attrib.get("r", "A1"); column=sum((ord(ch)-64)*26**i for i,ch in enumerate(reversed(re.match(r"[A-Z]+", ref).group()))) - 1
                kind=cell.attrib.get("t"); value=cell.findtext(ns + "v", "")
                if kind == "s" and value: value=shared[int(value)]
                elif kind == "inlineStr": value="".join(t.text or "" for t in cell.iter(ns + "t"))
                elif value and re.fullmatch(r"-?\d+(\.\d+)?", value): value=float(value) if "." in value else int(value)
                values[column]=value
            if values: output.append([values.get(i, "") for i in range(max(values)+1)])
    return output

@app.put("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, item: TransactionUpdate):
    with conn() as c:
        old = c.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not old: raise HTTPException(404, "Transaction not found")
        account = c.execute('SELECT * FROM accounts WHERE id=?',(item.account_id,)).fetchone()
        category = c.execute('SELECT name FROM categories WHERE id=?',(item.category_id,)).fetchone()
        if not account or (item.category_id is not None and not category): raise HTTPException(400,'Choose an existing account and category.')
        try: day = date.fromisoformat(item.date).isoformat()
        except ValueError: raise HTTPException(400,'Enter a valid date.')
        if not item.description.strip() or not math.isfinite(item.amount): raise HTTPException(400,'Enter a description and valid amount.')
        if item.status not in ('active','excluded'): raise HTTPException(400,'Invalid transaction status.')
        kind = item.kind or infer_kind(item.description,item.amount,account['type'],category[0] if category else None)
        if kind not in ('expense','income','credit','refund','repayment','transfer'): raise HTTPException(400,'Invalid transaction type.')
        if (kind in ('income','credit','refund') and item.amount<=0) or (kind=='expense' and item.amount>=0): raise HTTPException(400,'Transaction type does not match its amount.')
        status = 'excluded' if kind in ('transfer','repayment') else item.status
        audit_transaction(c,tx_id)
        if old['transfer_link'] and (item.account_id!=old['account_id'] or round(item.amount,2)!=old['amount'] or day!=old['date'] or kind!='transfer'):
            c.execute('UPDATE transactions SET transfer_link=NULL WHERE transfer_link=?',(old['transfer_link'],))
        c.execute("UPDATE transactions SET date=?,description=?,amount=?,account_id=?,category_id=?,status=?,edited_at=?,raw_hash=?,kind=? WHERE id=?", (day,item.description.strip(),round(item.amount,2),item.account_id,item.category_id,status,datetime.now().isoformat(timespec='seconds'),raw_hash(day,item.amount,item.description,account['name']),kind,tx_id))
        if item.create_rule and item.category_id:
            c.execute("INSERT INTO rules(merchant_pattern,category_id) VALUES(?,?) ON CONFLICT(merchant_pattern) DO UPDATE SET category_id=excluded.category_id", (item.description.strip(),item.category_id))
    return {"ok": True}

@app.post("/api/transactions/{tx_id}/delete")
def delete_transaction(tx_id: int):
    with conn() as c:
        audit_transaction(c,tx_id)
        c.execute("UPDATE transactions SET previous_status=status,status='deleted', deleted_at=? WHERE id=? AND status!='deleted'", (datetime.now().isoformat(timespec="seconds"),tx_id))
    return {"ok": True}
@app.post("/api/transactions/{tx_id}/restore")
def restore_transaction(tx_id: int):
    with conn() as c:
        audit_transaction(c,tx_id)
        c.execute("UPDATE transactions SET status=CASE WHEN kind IN ('transfer','repayment') THEN 'excluded' ELSE COALESCE(previous_status,'active') END, deleted_at=NULL WHERE id=? AND status='deleted'", (tx_id,))
    return {"ok": True}
@app.post("/api/transactions/{tx_id}/mark-card-payment")
def mark_card_payment(tx_id: int):
    with conn() as c:
        category = c.execute("SELECT id FROM categories WHERE name='Credit Card Payment'").fetchone()
        if not category: raise HTTPException(500, "Credit Card Payment category is missing")
        audit_transaction(c,tx_id)
        c.execute("UPDATE transactions SET category_id=?,kind='repayment', status='excluded', edited_at=? WHERE id=?", (category["id"], datetime.now().isoformat(timespec="seconds"), tx_id))
    return {"ok": True}
@app.post("/api/transactions/{tx_id}/mark-transfer")
def mark_transfer(tx_id: int, match_id: Optional[int] = None):
    with conn() as c:
        transaction = c.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not transaction: raise HTTPException(404, "Transaction not found")
        transfer_category = c.execute("SELECT id FROM categories WHERE name='Transfers'").fetchone()
        if not transfer_category: raise HTTPException(500, "Transfers category is missing")
        start = (datetime.fromisoformat(transaction["date"]).date() - timedelta(days=3)).isoformat()
        end = (datetime.fromisoformat(transaction["date"]).date() + timedelta(days=3)).isoformat()
        if transaction['status'] not in ('active','excluded'): raise HTTPException(400,'Restore or review this transaction first.')
        ids = [tx_id]
        if match_id is not None:
            other = c.execute('SELECT * FROM transactions WHERE id=?',(match_id,)).fetchone()
            if not other or other['id']==tx_id or other['account_id']==transaction['account_id'] or round(other['amount']+transaction['amount'],2)!=0 or other['status'] not in ('active','excluded') or other['transfer_link']:
                raise HTTPException(400,'Choose one unlinked, opposite transaction in another account for the same amount.')
            ids.append(match_id)
        if transaction['transfer_link']: raise HTTPException(400,'This transaction already has a linked transfer. Edit it to unlink first.')
        link = str(uuid.uuid4()) if len(ids)==2 else None
        for item in ids:
            audit_transaction(c,item)
            c.execute("UPDATE transactions SET category_id=?,kind='transfer',transfer_link=?, status='excluded', edited_at=? WHERE id=?", (transfer_category['id'],link,datetime.now().isoformat(),item))
    return {"ok": True, "linked": len(ids) - 1}
@app.post("/api/transactions/{tx_id}/review")
def resolve_review(tx_id: int, keep: bool = Form(...)):
    with conn() as c:
        c.execute("UPDATE transactions SET previous_status='review',status=CASE WHEN ? THEN CASE WHEN kind IN ('transfer','repayment') THEN 'excluded' ELSE 'active' END ELSE 'deleted' END WHERE id=? AND status='review'", (keep, tx_id))
    return {"ok": True}

def month_start(offset=0):
    today = date.today()
    index = today.year*12+today.month-1+offset
    return date(index//12,index%12+1,1)

@app.get('/api/month-breakdown')
def month_breakdown(month: str):
    try:
        if not re.fullmatch(r'\d{4}-\d{2}',month): raise ValueError()
        date.fromisoformat(month+'-01')
    except ValueError: raise HTTPException(400,'Choose a valid month.')
    data=tx_rows("t.status='active' AND substr(t.date,1,7)=? AND t.date<=? AND t.kind NOT IN ('transfer','repayment')",(month,date.today().isoformat()))
    expenses=[t for t in data if t['amount']<0]
    refunds=[t for t in data if t['amount']>0 and t['kind']=='refund']
    grouped={}
    for t in expenses+refunds:
        group=grouped.setdefault(t['category'],dict(category=t['category'],gross=0,refunds=0,count=0))
        if t['amount']<0: group['gross']+=-t['amount'];group['count']+=1
        else: group['refunds']+=t['amount']
    for g in grouped.values():
        g['gross']=round(g['gross'],2);g['refunds']=round(g['refunds'],2);g['net']=round(g['gross']-g['refunds'],2)
    categories=sorted(grouped.values(),key=lambda g:g['gross'],reverse=True)
    gross=round(-sum(t['amount'] for t in expenses),2);refund_total=round(sum(t['amount'] for t in refunds),2)
    food=grouped.get('Online food order',dict(gross=0,refunds=0,net=0,count=0))
    return dict(month=month,gross=gross,refunds=refund_total,net=round(gross-refund_total,2),categories=categories,top_category=categories[0]['category'] if categories and categories[0]['gross']>0 else None,online_food=food,transactions=expenses+refunds)

@app.get('/api/dashboard')
def dashboard():
    data = tx_rows("t.status='active' AND t.date>=? AND t.date<=? AND t.kind NOT IN ('transfer','repayment')",(month_start(-5).isoformat(),date.today().isoformat()))
    current = [t for t in data if t['date']>=month_start().isoformat()]
    expenses = [t for t in current if t['amount']<0]
    by_category=defaultdict(float); merchant=defaultdict(float)
    by_month={month_start(i).strftime('%Y-%m'):0 for i in range(-5,1)}
    for t in data:
        value = -t['amount'] if t['amount']<0 or t['kind']=='refund' else 0
        by_month[t['date'][:7]] += value
    for t in expenses:
        by_category[t['category']] += -t['amount']; merchant[t['description']] += -t['amount']
    gross = round(-sum(t['amount'] for t in expenses),2)
    refunds=round(sum(t['amount'] for t in current if t['kind']=='refund'),2)
    return dict(total_spend=round(gross-refunds,2),gross_spend=gross,refunds=refunds,month_label=date.today().strftime('%B %Y'),by_category=by_category,by_month=by_month,top_merchants=sorted(merchant.items(),key=lambda x:x[1],reverse=True)[:5],recurring=detect_recurring([t for t in data if t['amount']<0]),transaction_count=len(current))

@app.get("/api/cards")
def credit_card_spend(month: str = '', account_id: Optional[int] = None):
    where = "t.status IN ('active','excluded') AND a.type='credit_card'"
    args=[]
    if month:
        if not re.fullmatch(r'\d{4}-\d{2}',month): raise HTTPException(400,'Invalid month')
        where += ' AND substr(t.date,1,7)=?'; args.append(month)
    if account_id: where += ' AND a.id=?'; args.append(account_id)
    data = tx_rows(where,args)
    expenses = [x for x in data if x['status']=='active' and x['amount']<0 and x['kind'] not in ('transfer','repayment')]
    credits = [x for x in data if x['status']=='active' and x['amount']>0 and x['kind']=='refund']
    by_account = defaultdict(float)
    for item in expenses: by_account[item["account_name"]] += abs(item["amount"])
    gross=round(sum(abs(x['amount']) for x in expenses),2); refunds=round(sum(x['amount'] for x in credits),2)
    return dict(total_spend=gross, total_credits=refunds,net_spend=round(gross-refunds,2),repayments=round(sum(x['amount'] for x in data if x['kind']=='repayment' and x['amount']>0),2),unclassified_credits=round(sum(x['amount'] for x in data if x['kind']=='credit' and x['amount']>0),2),by_account=by_account,transactions=data)

def detect_recurring(items):
    groups = defaultdict(list)
    for x in items: groups[re.sub(r"\d+", "", x["description"].lower()).strip()].append(x)
    result=[]
    for name, xs in groups.items():
        xs.sort(key=lambda x:x["date"])
        if len(xs) >= 3:
            values=[abs(x["amount"]) for x in xs]
            intervals=[(date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days for a,b in zip(xs,xs[1:])]
            if max(values) <= min(values)*1.05 and all(25<=gap<=35 for gap in intervals):
                result.append({"merchant": xs[-1]["description"], "amount": round(sum(values)/len(values),2), "occurrences":len(xs)})
    return sorted(result, key=lambda x:x["amount"], reverse=True)

@app.get('/api/imports')
def import_history():
    return rows('SELECT i.*,a.name account,count(t.id) row_count FROM imports i LEFT JOIN accounts a ON a.id=i.account_id LEFT JOIN transactions t ON t.import_id=i.id GROUP BY i.id ORDER BY i.id DESC')

@app.post('/api/imports/{batch_id}/undo')
def undo_import(batch_id:int):
    with conn() as c:
        batch=c.execute('SELECT * FROM imports WHERE id=?',(batch_id,)).fetchone()
        if not batch: raise HTTPException(404,'Import not found')
        if batch['undone']: return {'ok':True}
        for t in c.execute("SELECT id FROM transactions WHERE import_id=? AND status!='deleted'",(batch_id,)).fetchall(): audit_transaction(c,t['id'])
        c.execute("UPDATE transactions SET previous_status=status,status='deleted',deleted_at=? WHERE import_id=? AND status!='deleted'",(datetime.now().isoformat(),batch_id))
        c.execute('UPDATE imports SET undone=1 WHERE id=?',(batch_id,))
        c.execute("UPDATE gmail_intake SET status='pending',import_id=NULL,preview_options=NULL,note='Import undone. Preview again to reimport, or dismiss this item.' WHERE import_id=?",(batch_id,))
    return {'ok':True}

@app.post('/api/imports/{batch_id}/move')
def move_import(batch_id:int, account_id:int=Form(...)):
    with conn() as c:
        account=c.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not account: raise HTTPException(400,'Account not found')
        if account['archived']: raise HTTPException(400,'Unarchive the destination account first.')
        if not c.execute('SELECT 1 FROM imports WHERE id=?',(batch_id,)).fetchone(): raise HTTPException(404,'Import not found')
        for t in c.execute('SELECT * FROM transactions WHERE import_id=?',(batch_id,)).fetchall():
            audit_transaction(c,t['id'])
            if t['transfer_link']: c.execute('UPDATE transactions SET transfer_link=NULL WHERE transfer_link=?',(t['transfer_link'],))
            h=raw_hash(t['date'],t['amount'],t['description'],account['name'])
            duplicate=c.execute("SELECT 1 FROM transactions WHERE id!=? AND import_id!=? AND (raw_hash=? OR source_hash=?) AND status!='deleted'",(t['id'],batch_id,h,h)).fetchone()
            status='review' if duplicate and t['status']!='deleted' else t['status']
            c.execute('UPDATE transactions SET account_id=?,raw_hash=?,status=? WHERE id=?',(account_id,h,status,t['id']))
        c.execute('UPDATE imports SET account_id=? WHERE id=?',(account_id,batch_id))
    return {'ok':True}

@app.post('/api/accounts/{account_id}/settings')
def account_settings(account_id:int,name:str=Form(...),archived:bool=Form(False)):
    with conn() as c:
        old=c.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
        if not old or not name.strip(): raise HTTPException(400,'Enter a valid account name')
        if c.execute('SELECT 1 FROM accounts WHERE name=? AND id!=?',(name.strip(),account_id)).fetchone(): raise HTTPException(400,'That name is already used')
        c.execute('INSERT OR REPLACE INTO account_aliases VALUES(?,?)',(old['name'],account_id))
        c.execute('UPDATE accounts SET name=?,archived=? WHERE id=?',(name.strip(),archived,account_id))
        for t in c.execute('SELECT * FROM transactions WHERE account_id=?',(account_id,)).fetchall():
            c.execute('UPDATE transactions SET raw_hash=? WHERE id=?',(raw_hash(t['date'],t['amount'],t['description'],name),t['id']))
    return {'ok':True}

@app.get('/api/export')
def export_transactions():
    buffer=io.StringIO(); writer=csv.writer(buffer)
    writer.writerow(['Date','Description','Amount','Account','Category','Type','Status','Source file'])
    for t in tx_rows("t.status IN ('active','excluded')"):
        values=[t['date'],t['description'],t['amount'],t['account_name'],t['category'],t['kind'],t['status'],t['source_file']]
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values])
    return Response('\ufeff'+buffer.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="ledger-transactions.csv"'})

@app.get('/api/backup')
def download_backup():
    folder=ROOT/'backups'; folder.mkdir(exist_ok=True)
    target=folder/('ledger-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.db')
    with sqlite3.connect(DB) as source, sqlite3.connect(target) as destination: source.backup(destination)
    return FileResponse(target,filename=target.name,media_type='application/octet-stream')

@app.get('/api/rules')
def list_rules():
    return rows('SELECT r.*,c.name category FROM rules r JOIN categories c ON c.id=r.category_id ORDER BY length(merchant_pattern) DESC,r.id')

@app.post('/api/rules')
def save_rule(pattern:str=Form(...),category_id:int=Form(...)):
    if not pattern.strip(): raise HTTPException(400,'Enter a description or merchant pattern.')
    with conn() as c:
        if not c.execute('SELECT 1 FROM categories WHERE id=?',(category_id,)).fetchone(): raise HTTPException(400,'Category not found')
        c.execute('INSERT INTO rules(merchant_pattern,category_id) VALUES(?,?) ON CONFLICT(merchant_pattern) DO UPDATE SET category_id=excluded.category_id',(pattern.strip(),category_id))
    return {'ok':True}

@app.delete('/api/rules/{rule_id}')
def delete_rule(rule_id:int):
    with conn() as c: c.execute('DELETE FROM rules WHERE id=?',(rule_id,))
    return {'ok':True}

@app.get('/api/coverage')
def coverage():
    return rows("SELECT a.name,MAX(t.date) latest FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id AND t.status IN ('active','excluded') WHERE a.archived=0 GROUP BY a.id ORDER BY a.name")


app.include_router(gmail_ingestion.bind(sys.modules[__name__]))
