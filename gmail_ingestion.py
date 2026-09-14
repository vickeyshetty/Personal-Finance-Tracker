"""Read-only Gmail intake. Remote content is untrusted; nothing follows email links."""
import base64
import hashlib
import io
import json
import re
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timezone
from email.utils import parseaddr
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit, quote

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool
import credential_store

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
SERVICE = 'Ledger.Gmail'
MAX_BYTES = 25 * 1024 * 1024
operation_lock = threading.Lock()
oauth_status = 'idle'
oauth_generation = 0
ledger = None


def init_schema(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS gmail_settings (
      id INTEGER PRIMARY KEY CHECK(id=1), vault_key TEXT NOT NULL,
      email TEXT NOT NULL, start_date TEXT NOT NULL, senders TEXT NOT NULL,
      cursor TEXT, last_sync TEXT);
    CREATE TABLE IF NOT EXISTS gmail_intake (
      id INTEGER PRIMARY KEY, mailbox TEXT NOT NULL, message_id TEXT NOT NULL,
      part_id TEXT NOT NULL, attachment_id TEXT, filename TEXT NOT NULL,
      sender TEXT NOT NULL, subject TEXT NOT NULL, received TEXT NOT NULL,
      status TEXT NOT NULL, note TEXT NOT NULL, excerpt TEXT NOT NULL DEFAULT '',
      content_hash TEXT, import_id INTEGER, UNIQUE(mailbox,message_id,part_id));
    ''')
    if 'preview_options' not in {r['name'] for r in c.execute('PRAGMA table_info(gmail_intake)')}:
        c.execute('ALTER TABLE gmail_intake ADD COLUMN preview_options TEXT')
    if 'auto_suppressed' not in {r['name'] for r in c.execute('PRAGMA table_info(gmail_intake)')}:
        c.execute('ALTER TABLE gmail_intake ADD COLUMN auto_suppressed INTEGER NOT NULL DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS email_account_links (
        issuer TEXT NOT NULL, account_type TEXT NOT NULL, last4 TEXT NOT NULL,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        PRIMARY KEY(issuer,account_type,last4))''')
    if 'all_senders' not in {r['name'] for r in c.execute('PRAGMA table_info(gmail_settings)')}:
        c.execute('ALTER TABLE gmail_settings ADD COLUMN all_senders INTEGER NOT NULL DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS gmail_statement_rules (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, sender TEXT NOT NULL,
        subject_keyword TEXT NOT NULL, filename_keyword TEXT NOT NULL,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        password_account_id INTEGER REFERENCES accounts(id))''')


def statement_route(c, item):
    if item['status']!='pending' or not item['filename'].lower().endswith('.pdf'):
        return None
    matches=[]
    for row in c.execute('''SELECT r.*,a.name account_name,p.name password_account_name
        FROM gmail_statement_rules r JOIN accounts a ON a.id=r.account_id
        LEFT JOIN accounts p ON p.id=r.password_account_id
        WHERE a.archived=0 AND (p.id IS NULL OR p.archived=0)'''):
        r=dict(row)
        if (item['sender'].lower()==r['sender'] and r['subject_keyword'] in item['subject'].lower()
                and r['filename_keyword'] in item['filename'].lower()): matches.append(r)
    if len(matches)>1: return {'ambiguous':True,'note':'Several statement rules match. Choose the account/password manually or narrow the rules.'}
    return matches[0] if matches else None


def sender_filter(s):
    return None if s['all_senders'] else json.loads(s['senders'])


class EmailText(HTMLParser):
    """Extract text without rendering HTML, executing scripts or loading images."""
    def __init__(self):
        super().__init__(); self.text=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.text.append(data)


def settings():
    with ledger.conn() as c:
        row = c.execute('SELECT * FROM gmail_settings WHERE id=1').fetchone()
    return dict(row) if row else None


def vault_read(key):
    value = credential_store.read(key, SERVICE)
    return json.loads(value) if value else None


def vault_save(key, value):
    credential_store.save(key, json.dumps(value), SERVICE)


def google_client():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession, Request as GoogleRequest
    s = settings()
    if not s: raise HTTPException(400, 'Configure Gmail first.')
    token = vault_read(s['vault_key'] + '-token')
    if not token: raise HTTPException(400, 'Connect Gmail first.')
    client=vault_read(s['vault_key']+'-client')['installed']
    # Access tokens can exceed Windows vault blob limits. Persist only the short
    # refresh token; obtain access tokens in memory for each operation.
    credentials = Credentials(token=None,refresh_token=token['refresh_token'],
        client_id=client['client_id'],client_secret=client['client_secret'],
        token_uri='https://oauth2.googleapis.com/token',scopes=[SCOPE])
    try:
        if not credentials.valid:
            credentials.refresh(GoogleRequest())
            vault_save(s['vault_key'] + '-token', {'refresh_token':credentials.refresh_token})
    except credential_store.VaultUnavailable:
        raise
    except Exception:
        raise HTTPException(401, 'Google authorization expired or could not be refreshed. Reconnect Gmail; no messages were imported.') from None
    return AuthorizedSession(credentials)


def get_json(session, path, params=None):
    # All requests go to a fixed Google API origin, never a URL from an email.
    response = session.get('https://gmail.googleapis.com/gmail/v1/users/me/' + path,
                           params=params, timeout=30, allow_redirects=False)
    if response.status_code != 200:
        code = response.status_code
        if code in (401,403): raise HTTPException(401, 'Gmail access denied. Check the Gmail API is enabled and reconnect with read-only access.')
        raise HTTPException(502, 'Gmail could not complete the request. Try again; completed items are retained.')
    return response.json()


def parts(payload):
    yield payload
    for part in payload.get('parts', []):
        yield from parts(part)


def decode(data):
    if len(data) > MAX_BYTES * 4 // 3 + 8: raise HTTPException(400, 'Attachment exceeds 25 MB.')
    try: return base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
    except Exception: raise HTTPException(400, 'Malformed Gmail attachment.') from None


def classify(payload, allowed):
    headers = {h['name'].lower(): h['value'] for h in payload.get('headers', [])}
    sender = parseaddr(headers.get('from', ''))[1].lower()
    subject = headers.get('subject', '')[:500]
    if allowed is not None and sender not in allowed:
        return sender, subject, [('message', None, '', 'ignored', 'Sender is not on your approved list.', '')]
    result=[]
    text=[]
    if re.search(r'\b(OTP|one.time password|verification code|security alert|verify your email|welcome to google)\b',subject,re.I):
        return sender,'Security / verification email',[('message',None,'','ignored','Security or verification message; not a transaction.','')]
    for index, part in enumerate(parts(payload)):
        filename=part.get('filename','')
        body=part.get('body',{})
        if filename.lower().endswith('.pdf'):
            if body.get('size',0)>MAX_BYTES:
                result.append((str(index),body.get('attachmentId'),filename[:200],'needs_review','PDF exceeds 25 MB.',''))
            else:
                result.append((str(index),body.get('attachmentId'),filename[:200],'pending','PDF awaiting account selection and preview.',''))
        elif part.get('mimeType') in ('text/plain','text/html') and not filename and body.get('data'):
            value=decode(body['data']).decode('utf-8',errors='replace')[:100000]
            if part.get('mimeType')=='text/html':
                parser=EmailText(); parser.feed(value); value=' '.join(parser.text)
            text.append(value[:10000])
    if result: return sender,subject,result
    plain='\n'.join(text)[:10000]
    combined=subject+' '+plain
    # Conservative classification only: alerts never become posted transactions.
    financial = bool(re.search(r'\b(debited|credited|spent|transaction|statement|payment received|refund)\b', combined, re.I))
    # Explicit enabled definitions may recognize wording outside the built-in keywords.
    import custom_parsers
    financial = financial or any(d['kind']=='email' and d['sender'].lower()==sender and d['contains'].lower() in plain.lower() for d in custom_parsers.enabled(ledger))
    # Do not persist OTPs, access links, or HTML bodies, even for financial candidates.
    note='Financial email without a PDF. Review in Gmail; HDFC statement downloads remain manual.' if financial else 'No supported statement or recognizable transaction alert.'
    return sender,subject,[('message',None,'','needs_review' if financial else 'ignored',note,'')]


def parse_transaction_alert(payload):
    import parsers
    headers={h['name'].lower():h['value'] for h in payload.get('headers',[])}
    sender=parseaddr(headers.get('from',''))[1].lower()
    texts=[]
    for part in parts(payload):
        if part.get('filename') or part.get('mimeType') not in ('text/plain','text/html'): continue
        data=part.get('body',{}).get('data')
        if not data: continue
        value=decode(data).decode('utf-8',errors='replace')[:100000]
        if part.get('mimeType')=='text/html':
            parser=EmailText();parser.feed(value);value=' '.join(parser.text)
        texts.append(re.sub(r'\s+',' ',value))
    try:
        import custom_parsers
        custom=custom_parsers.email(ledger,sender,headers.get('subject',''),' '.join(texts))
        if custom is not None: return custom
        return parsers.parse_email(sender,headers.get('subject',''),' '.join(texts))
    except (ValueError,ArithmeticError): raise HTTPException(400,'No single supported transaction was found in this email. Unsupported, invalid or ambiguous alerts remain in review.') from None


def parse_indusind_alert(payload):
    # Compatibility entry point; all parsing now uses the trusted registry.
    return parse_transaction_alert(payload)


def read_alert(item):
    s=settings()
    if not s or s['email']!=item['mailbox']: raise HTTPException(400,'Connect the mailbox this email belongs to.')
    allowed=sender_filter(s)
    if allowed is not None and item['sender'] not in allowed: raise HTTPException(400,'Sender is not approved.')
    with google_client() as session:
        message=get_json(session,'messages/'+quote(item['message_id'],safe=''),{'format':'full'})
    headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
    if parseaddr(headers.get('from',''))[1].lower()!=item['sender']: raise HTTPException(400,'Email sender changed. Sync and review again.')
    return parse_transaction_alert(message.get('payload',{}))


def alert_candidates(c,account_id,parsed):
    return [dict(r) for r in c.execute("""SELECT id,date,description,amount,status FROM transactions
        WHERE account_id=? AND status!='deleted' AND abs(amount-?)<0.005
        AND abs(julianday(date)-julianday(?))<=3 ORDER BY date,id""",(account_id,parsed['amount'],parsed['date']))]


def confirmed_alert_account(c,p):
    linked=c.execute('''SELECT a.* FROM email_account_links l JOIN accounts a ON a.id=l.account_id
        WHERE l.issuer=? AND l.account_type=? AND l.last4=? AND a.type=? AND a.archived=0''',
        (p['issuer'],p['account_type'],p['account_last4'],p['account_type'])).fetchone()
    if linked: return linked
    if p['account_type']=='credit_card':
        return c.execute("SELECT a.* FROM card_identities i JOIN accounts a ON a.id=i.account_id WHERE i.issuer=? AND i.last4=? AND a.type='credit_card' AND a.archived=0",(p['issuer'],p['account_last4'])).fetchone()
    return None


def auto_process_alert(c,item,payload):
    if item['status']!='needs_review' or item['filename'] or item['auto_suppressed']: return 'skipped'
    try: p=parse_transaction_alert(payload)
    except HTTPException:
        c.execute("UPDATE gmail_intake SET note='Unsupported or ambiguous alert; not added. Use preview for details.' WHERE id=?",(item['id'],))
        return 'unsupported'
    account=confirmed_alert_account(c,p)
    if not account:
        c.execute("UPDATE gmail_intake SET note='Account ownership not confirmed. Preview and confirm once to enable automatic routing for this account ending.' WHERE id=?",(item['id'],))
        return 'review'
    matches=alert_candidates(c,account['id'],p)
    status='review' if matches else 'active'
    marker=hashlib.sha256((item['mailbox']+'|'+item['message_id']).encode()).hexdigest()[:24]
    batch=c.execute('INSERT INTO imports(filename,account_id,created_at) VALUES(?,?,?)',('email-alert-'+marker,account['id'],datetime.now().isoformat())).lastrowid
    category=ledger.categorise(p['description'],c)
    fingerprint=ledger.raw_hash(p['date'],p['amount'],p['description'],account['name'])
    original=dict(date=p['date'],amount=p['amount'],description=p['description'],category_id=category,kind=p['kind'],status='active')
    c.execute('''INSERT INTO transactions(date,description,amount,account_id,category_id,status,source_file,raw_hash,source_hash,import_id,kind,previous_status,source_type,duplicate_of,email_original)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(p['date'],p['description'],p['amount'],account['id'],category,status,'Email alert · '+p['parser_id'],fingerprint,fingerprint,batch,p['kind'],'active','email',matches[0]['id'] if matches else None,json.dumps(original)))
    c.execute("UPDATE gmail_intake SET status='imported',import_id=?,note=?,preview_options=NULL WHERE id=?",(batch,'Possible duplicate sent to transaction Review.' if matches else 'Automatically added as an email/provisional transaction.',item['id']))
    return 'review' if matches else 'added'


def stage_message(c, mailbox, message, allowed):
    sender,subject,items=classify(message.get('payload',{}),allowed)
    received=datetime.fromtimestamp(int(message.get('internalDate','0'))/1000, timezone.utc).isoformat()
    count=0
    for part,attachment,filename,status,note,excerpt in items:
        result=c.execute('''INSERT OR IGNORE INTO gmail_intake
          (mailbox,message_id,part_id,attachment_id,filename,sender,subject,received,status,note,excerpt)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
          (mailbox,message['id'],part,attachment,filename,sender,subject,received,status,note,excerpt))
        count += result.rowcount
    return count


def download_item(item):
    s=settings()
    if not s or s['email']!=item['mailbox']: raise HTTPException(400,'Connect the mailbox this item belongs to.')
    allowed=sender_filter(s)
    if allowed is not None and item['sender'] not in allowed: raise HTTPException(400,'This sender is no longer approved.')
    with google_client() as session:
        message=get_json(session,'messages/'+quote(item['message_id'],safe=''),{'format':'full'})
        # Re-evaluate current message, not a URL or attachment ID supplied by the browser.
        _,_,candidates=classify(message['payload'],allowed)
        candidate=next((x for x in candidates if x[0]==item['part_id'] and x[3]=='pending'),None)
        if not candidate: raise HTTPException(400,'This PDF is no longer eligible. Check the original message.')
        part=list(parts(message['payload']))[int(item['part_id'])]
        body=part.get('body',{})
        if body.get('attachmentId'):
            body=get_json(session,'messages/'+quote(item['message_id'],safe='')+'/attachments/'+quote(body['attachmentId'],safe=''))
        content=decode(body.get('data',''))
    if len(content)>MAX_BYTES or not content.startswith(b'%PDF-'):
        raise HTTPException(400,'Attachment is not a valid PDF or exceeds 25 MB.')
    return content


def bind(module):
    global ledger
    ledger=module
    router=APIRouter(prefix='/api/gmail')

    @router.get('/statement-rules')
    def statement_rules():
        return ledger.rows('''SELECT r.*,a.name account_name,p.name password_account_name FROM gmail_statement_rules r
            JOIN accounts a ON a.id=r.account_id LEFT JOIN accounts p ON p.id=r.password_account_id ORDER BY r.id DESC''')

    @router.post('/statement-rules')
    async def save_statement_rule(request:Request):
        try:
            d=await request.json()
            name=d['name'].strip(); sender=d['sender'].strip().lower()
            subject=d.get('subject_keyword','').strip().lower(); filename=d.get('filename_keyword','').strip().lower()
            account=int(d['account_id']); password=int(d['password_account_id']) if d.get('password_account_id') else None
            rule_id=int(d['id']) if d.get('id') else None
            if not name or len(name)>80 or len(sender)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',sender) or not(subject or filename) or max(len(subject),len(filename))>200: raise ValueError()
        except Exception: raise HTTPException(400,'Enter a rule name, exact sender address, and at least one subject or filename keyword.') from None
        with ledger.conn() as c:
            for account_id in (account,password):
                if account_id is not None and not c.execute('SELECT 1 FROM accounts WHERE id=? AND archived=0',(account_id,)).fetchone(): raise HTTPException(400,'Choose an active account.')
            if rule_id:
                if not c.execute('SELECT 1 FROM gmail_statement_rules WHERE id=?',(rule_id,)).fetchone(): raise HTTPException(404,'Rule not found.')
                c.execute('UPDATE gmail_statement_rules SET name=?,sender=?,subject_keyword=?,filename_keyword=?,account_id=?,password_account_id=? WHERE id=?',(name,sender,subject,filename,account,password,rule_id))
            else:
                rule_id=c.execute('INSERT INTO gmail_statement_rules(name,sender,subject_keyword,filename_keyword,account_id,password_account_id) VALUES(?,?,?,?,?,?)',(name,sender,subject,filename,account,password)).lastrowid
            # Changed rules require a fresh preview, but never alter posted transactions.
            c.execute("UPDATE gmail_intake SET preview_options=NULL WHERE status='pending'")
        return {'ok':True,'id':rule_id}

    @router.delete('/statement-rules/{rule_id}')
    def delete_statement_rule(rule_id:int):
        with ledger.conn() as c:
            c.execute('DELETE FROM gmail_statement_rules WHERE id=?',(rule_id,))
            c.execute("UPDATE gmail_intake SET preview_options=NULL WHERE status='pending'")
        return {'ok':True}

    @router.get('/status')
    def status():
        s=settings()
        if not s: return {'configured':False,'connected':False,'oauth_status':oauth_status}
        return {'configured':True,'connected':bool(vault_read(s['vault_key']+'-token')),
                'email':s['email'],'start_date':s['start_date'],'senders':json.loads(s['senders']),
                'all_senders':bool(s['all_senders']),
                'last_sync':s['last_sync'],'has_more':bool(s['cursor']),'oauth_status':oauth_status}

    @router.post('/configure')
    async def configure(request:Request):
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is in progress.')
        try:
            raw=await request.body()
            if len(raw)>20000: raise HTTPException(400,'Configuration is too large.')
            try:
                data=json.loads(raw)
                client=data['client']['installed']
                email=data['email'].strip().lower()
                start=date.fromisoformat(data['start_date']).isoformat() if data.get('start_date') else ''
                all_senders=data.get('all_senders',False)
                if not isinstance(all_senders,bool): raise ValueError()
                senders=sorted(set(x.strip().lower() for x in data.get('senders',[])))
                if not re.fullmatch(r'[^\s@]+@[^\s@]+',email): raise ValueError()
                if (not all_senders and not senders) or len(senders)>100 or any(not re.fullmatch(r'[^\s@]+@[^\s@]+',s) for s in senders): raise ValueError()
                if not client['client_id'].endswith('.apps.googleusercontent.com'): raise ValueError()
                if not isinstance(client['client_secret'],str) or len(client['client_secret'])>500: raise ValueError()
            except Exception: raise HTTPException(400,'Provide Desktop OAuth client JSON and a mailbox address. Choose all senders or supply exact sender addresses; the start date is optional.') from None
            # Never trust arbitrary OAuth URLs from an uploaded JSON file.
            clean={'installed':{'client_id':client['client_id'],'client_secret':client['client_secret'],
                'auth_uri':'https://accounts.google.com/o/oauth2/auth',
                'token_uri':'https://oauth2.googleapis.com/token','redirect_uris':['http://localhost']}}
            old=settings()
            key=old['vault_key'] if old else str(uuid.uuid4())
            if old and (old['email']!=email or vault_read(key+'-client')!=clean):
                credential_store.remove(key+'-token',SERVICE)
            vault_save(key+'-client',clean)
            with ledger.conn() as c:
                c.execute('''INSERT INTO gmail_settings(id,vault_key,email,start_date,senders,all_senders) VALUES(1,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET email=excluded.email,start_date=excluded.start_date,senders=excluded.senders,all_senders=excluded.all_senders,cursor=NULL''',
                  (key,email,start,json.dumps(senders),int(all_senders)))
                c.execute("DELETE FROM gmail_intake WHERE mailbox=? AND status='ignored'",(email,))
            return {'ok':True}
        finally: operation_lock.release()

    @router.post('/connect')
    def connect():
        global oauth_status,oauth_generation
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is already in progress.')
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            s=settings()
            if not s: raise HTTPException(400,'Configure Gmail first.')
            flow=InstalledAppFlow.from_client_config(vault_read(s['vault_key']+'-client'),[SCOPE],autogenerate_code_verifier=True)
            expected_state=secrets.token_urlsafe(32)
            oauth_generation+=1
            generation=oauth_generation

            class Callback(BaseHTTPRequestHandler):
                def log_message(self,*args): pass  # Callback URLs contain authorization codes.
                def do_GET(self):
                    global oauth_status
                    query=parse_qs(urlsplit(self.path).query)
                    valid=(urlsplit(self.path).path=='/callback' and secrets.compare_digest(query.get('state',[''])[0],expected_state))
                    if not valid:
                        self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid authorization response.'); return
                    try:
                        if generation!=oauth_generation or 'error' in query: raise ValueError()
                        flow.fetch_token(code=query['code'][0],timeout=30)
                        granted=flow.credentials.granted_scopes
                        if granted is not None and set(granted)!={SCOPE}: raise ValueError()
                        from google.auth.transport.requests import AuthorizedSession
                        with AuthorizedSession(flow.credentials) as session:
                            profile=get_json(session,'profile')
                        if profile['emailAddress'].lower()!=s['email']:
                            oauth_status='wrong_mailbox'
                        else:
                            if not flow.credentials.refresh_token: raise ValueError()
                            vault_save(s['vault_key']+'-token',{'refresh_token':flow.credentials.refresh_token})
                            oauth_status='connected'
                    except Exception: oauth_status='failed'
                    self.server.finished=True
                    self.send_response(200); self.send_header('Content-Type','text/plain'); self.end_headers()
                    self.wfile.write(b'Return to Ledger to check connection status. You may close this tab.')

            server=HTTPServer(('127.0.0.1',0),Callback)
            server.timeout=1
            server.finished=False
            flow.redirect_uri=f'http://127.0.0.1:{server.server_port}/callback'
            url,_=flow.authorization_url(state=expected_state,access_type='offline',prompt='consent',login_hint=s['email'],include_granted_scopes='false')
            oauth_status='waiting'
            def wait_callback():
                global oauth_status
                try:
                    deadline=time.monotonic()+300
                    while not server.finished and time.monotonic()<deadline:
                        server.handle_request()
                    if not server.finished: oauth_status='timed_out'
                finally:
                    server.server_close()
                    operation_lock.release()
            threading.Thread(target=wait_callback,daemon=True).start()
            return {'authorization_url':url}
        except Exception:
            operation_lock.release()
            raise HTTPException(400,'Could not start Google sign-in. Check configuration and installed dependencies.') from None

    @router.post('/disconnect')
    def disconnect():
        global oauth_status
        if not operation_lock.acquire(False): raise HTTPException(409,'Wait for the current sync/sign-in to finish (sign-in times out after five minutes).')
        try:
            s=settings()
            if s: credential_store.remove(s['vault_key']+'-token',SERVICE)
            oauth_status='disconnected'
            return {'ok':True,'note':'Local token removed. You can also revoke Ledger access in your Google Account permissions.'}
        finally: operation_lock.release()

    @router.post('/sync')
    def sync():
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is in progress.')
        try:
            s=settings()
            if not s: raise HTTPException(400,'Configure Gmail first.')
            # Gmail interprets date strings in Pacific time; use local-midnight
            # epoch seconds so an Indian morning is not silently missed.
            params={'maxResults':50}
            if s['start_date']:
                start=int(datetime.fromisoformat(s['start_date']).astimezone().timestamp())-1
                params['q']='after:'+str(start)
            if s['cursor']: params['pageToken']=s['cursor']
            count=0
            summary={'added':0,'review':0,'ignored':0,'unsupported':0,'skipped':0,'statements':0}
            processed=set()
            with google_client() as session:
                result=get_json(session,'messages',params)
                message_ids=[i['id'] for i in result.get('messages',[])]
                # Also revisit already-collected alerts, including those awaiting an account link.
                with ledger.conn() as c:
                    backlog=[r['message_id'] for r in c.execute("SELECT message_id FROM gmail_intake WHERE mailbox=? AND filename='' AND status='needs_review' AND auto_suppressed=0 ORDER BY id LIMIT 50",(s['email'],))]
                for message_id in list(dict.fromkeys(message_ids+backlog)):
                    if message_id in processed: continue
                    processed.add(message_id)
                    with ledger.conn() as c:
                        seen=c.execute('SELECT * FROM gmail_intake WHERE mailbox=? AND message_id=?',(s['email'],message_id)).fetchall()
                    if seen and all(r['status']!='needs_review' or r['auto_suppressed'] for r in seen):
                        summary['skipped']+=1
                        continue
                    message=get_json(session,'messages/'+quote(message_id,safe=''),{'format':'metadata','metadataHeaders':['From','Subject']})
                    headers={h['name'].lower():h['value'] for h in message.get('payload',{}).get('headers',[])}
                    allowed=sender_filter(s)
                    eligible=allowed is None or parseaddr(headers.get('from',''))[1].lower() in allowed
                    if eligible:
                        message=get_json(session,'messages/'+quote(message_id,safe=''),{'format':'full'})
                    with ledger.conn() as c:
                        c.execute('BEGIN IMMEDIATE')
                        count+=stage_message(c,s['email'],message,allowed)
                        current=c.execute('SELECT * FROM gmail_intake WHERE mailbox=? AND message_id=?',(s['email'],message_id)).fetchall()
                        for item in current:
                            if item['status']=='ignored': summary['ignored']+=1
                            elif item['status']=='pending' and item['filename']: summary['statements']+=1
                            elif eligible and item['status']=='needs_review':
                                # Recheck current security classification before parsing.
                                classified=classify(message.get('payload',{}),allowed)
                                if not any(x[3]=='needs_review' and not x[2] for x in classified[2]):
                                    summary['review']+=1
                                    continue
                                summary[auto_process_alert(c,item,message.get('payload',{}))]+=1
                            else: summary['skipped']+=1
            with ledger.conn() as c:
                c.execute('UPDATE gmail_settings SET cursor=?,last_sync=? WHERE id=1',(result.get('nextPageToken'),datetime.now(timezone.utc).isoformat()))
            return {'staged':count,'has_more':bool(result.get('nextPageToken')),**summary}
        except HTTPException: raise
        except credential_store.VaultUnavailable: raise
        except Exception: raise HTTPException(502,'Sync interrupted. Retry safely; completed messages will not be added twice.') from None
        finally: operation_lock.release()

    @router.get('/items')
    def items():
        with ledger.conn() as c:
            result=[dict(r) for r in c.execute("SELECT * FROM gmail_intake ORDER BY CASE WHEN status IN ('pending','needs_review') THEN 0 ELSE 1 END,received DESC,id DESC LIMIT 500")]
            for item in result: item['routing']=statement_route(c,item)
            return result

    @router.post('/items/{item_id}/dismiss')
    def dismiss(item_id:int):
        with ledger.conn() as c:
            c.execute("UPDATE gmail_intake SET status='dismissed' WHERE id=? AND import_id IS NULL",(item_id,))
        return {'ok':True}

    @router.get('/parsers')
    def parser_catalog():
        import parsers
        return {'parsers':parsers.catalog(),'policy':'Trusted built-in modules only. No uploaded code is executed.'}

    @router.post('/items/{item_id}/alert-preview')
    async def alert_preview(item_id:int,request:Request):
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is in progress.')
        try:
            with ledger.conn() as c: row=c.execute('SELECT * FROM gmail_intake WHERE id=?',(item_id,)).fetchone()
            if not row: raise HTTPException(404,'Email item not found.')
            item=dict(row)
            if item['filename'] or item['status']!='needs_review': raise HTTPException(400,'Select a transaction email awaiting review.')
            result=await run_in_threadpool(read_alert,item)
            try: choices=await request.json() if await request.body() else {}
            except Exception: raise HTTPException(400,'Invalid preview choices.') from None
            with ledger.conn() as c:
                account=confirmed_alert_account(c,result)
                if choices.get('account_id'):
                    account=c.execute('SELECT id,name FROM accounts WHERE id=? AND type=? AND archived=0',(choices['account_id'],result['account_type'])).fetchone()
                    if not account: raise HTTPException(400,'Choose an active account of the correct type.')
                elif not account and result['account_type']=='credit_card':
                    account=c.execute('SELECT a.id,a.name FROM card_identities i JOIN accounts a ON a.id=i.account_id WHERE i.issuer=? AND i.last4=? AND a.archived=0',(result['issuer'],result['account_last4'])).fetchone()
                elif not account and result['issuer']=='idfc':
                    candidates=c.execute("SELECT id,name FROM accounts WHERE type='bank' AND archived=0 AND lower(name) LIKE '%idfc%'").fetchall()
                    if len(candidates)==1: account=candidates[0]
                result['account_id']=account['id'] if account else None
                result['account_name']=account['name'] if account else None
                result['category_id']=ledger.categorise(result['description'],c)
                result['matches']=alert_candidates(c,account['id'],result) if account else []
                result['preview_token']=secrets.token_urlsafe(24)
                snapshot={'parsed':result,'expires':time.time()+1800}
                c.execute('UPDATE gmail_intake SET preview_options=? WHERE id=?',(json.dumps(snapshot),item_id))
            return result
        finally: operation_lock.release()

    @router.post('/items/{item_id}/alert-confirm')
    async def alert_confirm(item_id:int,request:Request):
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is in progress.')
        try:
            try: data=await request.json()
            except Exception: raise HTTPException(400,'Invalid confirmation.') from None
            with ledger.conn() as c:
                c.execute('BEGIN IMMEDIATE')
                item=c.execute('SELECT * FROM gmail_intake WHERE id=?',(item_id,)).fetchone()
                if not item: raise HTTPException(404,'Email item not found.')
                if item['status']=='imported': return {'already_imported':True,'import_id':item['import_id']}
                if item['filename'] or item['status']!='needs_review': raise HTTPException(400,'This alert is not awaiting review.')
                s=settings()
                if not s or s['email']!=item['mailbox'] or (sender_filter(s) is not None and item['sender'] not in sender_filter(s)): raise HTTPException(400,'Mailbox or sender configuration changed. Preview again.')
                try:
                    snapshot=json.loads(item['preview_options']);p=snapshot['parsed']
                    if snapshot['expires']<time.time() or not secrets.compare_digest(str(data.get('preview_token','')),p['preview_token']): raise ValueError()
                except (TypeError,KeyError,ValueError): raise HTTPException(409,'Preview this email again before confirming.') from None
                try: account_id=int(data['account_id']);category_id=int(data['category_id'])
                except (TypeError,KeyError,ValueError): raise HTTPException(400,'Choose an account and category.') from None
                if account_id!=p['account_id']: raise HTTPException(409,'Account changed. Preview again to check duplicates.')
                account=c.execute('SELECT * FROM accounts WHERE id=? AND type=? AND archived=0',(account_id,p['account_type'])).fetchone()
                if not account or not c.execute('SELECT 1 FROM categories WHERE id=?',(category_id,)).fetchone(): raise HTTPException(400,'Choose an active account and existing category.')
                kind=data.get('kind',p['kind']);description=data.get('description',p['description'])
                if kind not in ('expense','income','credit','refund','repayment','transfer') or not isinstance(description,str) or not 1<=len(description.strip())<=1000: raise HTTPException(400,'Check transaction type and description.')
                if (kind in ('income','credit','refund') and p['amount']<0) or (kind=='expense' and p['amount']>0): raise HTTPException(400,'Transaction type does not match debit/credit direction.')
                matches=alert_candidates(c,account_id,p)
                existing_link=confirmed_alert_account(c,p)
                if existing_link and existing_link['id']!=account_id: raise HTTPException(409,'This account ending is already linked to a different account. Resolve the ownership mapping before confirming.')
                c.execute('INSERT INTO email_account_links(issuer,account_type,last4,account_id) VALUES(?,?,?,?) ON CONFLICT(issuer,account_type,last4) DO UPDATE SET account_id=excluded.account_id',(p['issuer'],p['account_type'],p['account_last4'],account_id))
                status='review' if matches else ('excluded' if kind in ('transfer','repayment') else 'active')
                marker=hashlib.sha256((item['mailbox']+'|'+item['message_id']).encode()).hexdigest()[:24]
                batch=c.execute('INSERT INTO imports(filename,account_id,created_at) VALUES(?,?,?)',('email-alert-'+marker,account_id,datetime.now().isoformat())).lastrowid
                description=description.strip()
                fingerprint=ledger.raw_hash(p['date'],p['amount'],description,account['name'])
                tx_id=c.execute("""INSERT INTO transactions(date,description,amount,account_id,category_id,status,source_file,raw_hash,source_hash,import_id,kind,previous_status,source_type,duplicate_of)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(p['date'],description,p['amount'],account_id,category_id,status,'Email alert · '+p['parser_id'],fingerprint,fingerprint,batch,kind,'excluded' if kind in ('transfer','repayment') else 'active','email',matches[0]['id'] if matches else None)).lastrowid
                original=dict(date=p['date'],amount=p['amount'],description=p['description'],category_id=p['category_id'],kind=p['kind'],status='active')
                c.execute('UPDATE transactions SET email_original=? WHERE id=?',(json.dumps(original),tx_id))
                c.execute("UPDATE gmail_intake SET status='imported',import_id=?,note=?,preview_options=NULL WHERE id=?",(batch,'Email transaction saved as provisional. Account ending confirmed for future automatic sync.',item_id))
            return {'transaction_id':tx_id,'import_id':batch,'review':bool(matches),'account':account['name'],'provisional':True}
        finally: operation_lock.release()

    @router.post('/items/{item_id}/preview')
    @router.post('/items/{item_id}/confirm')
    async def process(item_id:int,request:Request):
        if not operation_lock.acquire(False): raise HTTPException(409,'A Gmail operation is in progress.')
        try:
            with ledger.conn() as c:
                row=c.execute('SELECT * FROM gmail_intake WHERE id=?',(item_id,)).fetchone()
            if not row: raise HTTPException(404,'Email item not found.')
            item=dict(row)
            if item['status'] in ('ignored','dismissed'): raise HTTPException(400,'This email item has been ignored or dismissed.')
            if not item['filename']: raise HTTPException(400,'This email has no PDF to import.')
            try:
                data=await request.json()
                account_id=int(data['account_id'])
                password_id=int(data['password_account_id']) if data.get('password_account_id') else None
            except Exception: raise HTTPException(400,'Select a destination account.') from None
            preview=request.url.path.endswith('/preview')
            # Stable source name allows recovery if the process stopped after committing an import.
            marker=hashlib.sha256((item['mailbox']+'|'+item['message_id']+'|'+item['part_id']).encode()).hexdigest()[:24]
            filename='gmail-'+marker+'-'+item['filename']
            with ledger.conn() as c:
                existing=c.execute('SELECT id FROM imports WHERE filename=? AND undone=0',(filename,)).fetchone()
            if existing:
                with ledger.conn() as c:
                    c.execute("UPDATE gmail_intake SET status='imported',import_id=?,note='Previously imported; recovered on retry.' WHERE id=?",(existing['id'],item_id))
                return {'already_imported':True,'import_id':existing['id']}
            choices=json.dumps({'account_id':account_id,'password_account_id':password_id,'override':bool(data.get('override',False))},sort_keys=True)
            content=await run_in_threadpool(download_item,item)
            digest=hashlib.sha256(content).hexdigest()
            if not preview:
                if not item['content_hash'] or digest!=item['content_hash'] or choices!=item['preview_options']:
                    raise HTTPException(409,'Preview this attachment before confirming.')
                with ledger.conn() as c:
                    duplicate=c.execute('''SELECT g.id FROM gmail_intake g JOIN imports i ON i.id=g.import_id
                      WHERE g.content_hash=? AND i.undone=0 AND g.id!=?''',(digest,item_id)).fetchone()
                if duplicate: raise HTTPException(409,'This exact PDF was already imported from another email.')
            result=await ledger.import_csv(account_id=account_id,file=UploadFile(io.BytesIO(content),filename=filename),
                preview=preview,override=bool(data.get('override',False)),password_account_id=password_id)
            with ledger.conn() as c:
                c.execute('UPDATE gmail_intake SET content_hash=?,status=?,import_id=?,note=?,preview_options=? WHERE id=?',
                    (digest,'pending' if preview else 'imported',None if preview else result['import_id'],
                     'Preview ready. Check the destination and totals.' if preview else 'Imported; undo is available in Import history.',choices,item_id))
            return result
        finally: operation_lock.release()

    return router
