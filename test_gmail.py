import base64
import json
import unittest
import urllib.request
import urllib.error
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch, MagicMock
from test_app import LedgerTests
import app
import gmail_ingestion as gmail


def mail(message_id='one', sender='statements@bank.example', pdf=True, text='Statement available'):
    payload={'headers':[{'name':'From','value':sender},{'name':'Subject','value':'Monthly statement'}],
             'parts':[{'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(text.encode()).decode()}}]}
    if pdf: payload['parts'].append({'filename':'statement.pdf','mimeType':'application/pdf','body':{'attachmentId':'att1','size':100}})
    return {'id':message_id,'internalDate':'1785542400000','payload':payload}


class GmailTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self)
        self.client.headers['X-Ledger-Token']=app.LOCAL_TOKEN
        self.vault={}
        self.patches=[patch.object(gmail,'vault_read',side_effect=lambda k:self.vault.get(k)),
                      patch.object(gmail,'vault_save',side_effect=lambda k,v:self.vault.update({k:v})),
                      patch.object(gmail.credential_store,'remove',side_effect=lambda k,*a:self.vault.pop(k,None))]
        for p in self.patches:p.start()
        self.config={'client':{'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'synthetic-secret',
                     'auth_uri':'https://evil.example','token_uri':'https://evil.example'}},
                     'email':'inbox@example.com','start_date':'2026-08-01','senders':['statements@bank.example']}
        self.assertEqual(self.client.post('/api/gmail/configure',json=self.config).status_code,200)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        LedgerTests.tearDown(self)

    def stage(self,message=None):
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',message or mail(),self.config['senders'])
            return c.execute('SELECT id FROM gmail_intake WHERE filename!=?',('',)).fetchone()[0]

    def test_configuration_secret_is_vault_only_and_urls_fixed(self):
        self.assertNotIn(b'synthetic-secret',app.DB.read_bytes())
        config=next(iter(self.vault.values()))['installed']
        self.assertEqual(config['token_uri'],'https://oauth2.googleapis.com/token')
        self.assertNotIn('client_secret',self.client.get('/api/gmail/status').text)
        r=self.client.get('/api/gmail/status',headers={'X-Ledger-Token':''})
        self.assertEqual(r.status_code,403)

    def test_unapproved_sender_ignored_and_alerts_never_posted(self):
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',mail(sender='stranger@example.com'),self.config['senders'])
            gmail.stage_message(c,'inbox@example.com',mail('alert',pdf=False,text='Account debited INR 500'),self.config['senders'])
            records=c.execute('SELECT status FROM gmail_intake ORDER BY id').fetchall()
            self.assertEqual([r['status'] for r in records],['ignored','needs_review'])
            self.assertEqual(c.execute('SELECT count(*) FROM transactions').fetchone()[0],0)

    def test_message_retry_idempotent_and_nested_pdf(self):
        message=mail()
        message['payload']={'parts':[message['payload']], 'headers':message['payload']['headers']}
        self.stage(message);self.stage(message)
        with app.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM gmail_intake').fetchone()[0],1)

    def test_preview_confirm_retry_and_account_binding(self):
        id=self.stage()
        data={'account_id':1,'password_account_id':None,'override':False}
        with patch.object(gmail,'download_item',return_value=b'%PDF-synthetic'),patch.object(app,'read_statement',return_value=[{'Date':'2026-08-01','Description':'Example','Amount':-50}]),patch.object(app,'automatic_statement_account',return_value=None):
            self.assertEqual(self.client.post(f'/api/gmail/items/{id}/confirm',json=data).status_code,409)
            r=self.client.post(f'/api/gmail/items/{id}/preview',json=data)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(len(app.bootstrap()['transactions']),0)
            self.assertEqual(self.client.post(f'/api/gmail/items/{id}/confirm',json={**data,'account_id':2}).status_code,409)
            r=self.client.post(f'/api/gmail/items/{id}/confirm',json=data)
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(len(app.bootstrap()['transactions']),1)
            r=self.client.post(f'/api/gmail/items/{id}/confirm',json=data)
            self.assertTrue(r.json()['already_imported'])
            self.assertEqual(len(app.bootstrap()['transactions']),1)

    def test_duplicate_attachment_across_messages(self):
        first=self.stage()
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',mail('two'),self.config['senders'])
            second=c.execute("SELECT id FROM gmail_intake WHERE message_id='two'").fetchone()[0]
        with patch.object(gmail,'download_item',return_value=b'%PDF-same'),patch.object(app,'read_statement',return_value=[{'Date':'2026-08-01','Description':'Example','Amount':-50}]),patch.object(app,'automatic_statement_account',return_value=None):
            for id in [first,second]:
                self.assertEqual(self.client.post(f'/api/gmail/items/{id}/preview',json={'account_id':1}).status_code,200)
            self.assertEqual(self.client.post(f'/api/gmail/items/{first}/confirm',json={'account_id':1}).status_code,200)
            self.assertEqual(self.client.post(f'/api/gmail/items/{second}/confirm',json={'account_id':1}).status_code,409)

    def test_sync_metadata_first_pagination_retry(self):
        allowed=mail('approved');unknown=mail('unknown',sender='outsider@example.com')
        calls=[]
        def get(session,path,params=None):
            calls.append((path,params))
            if path=='messages':return {'messages':[{'id':'approved'},{'id':'unknown'}],'nextPageToken':'page2'}
            return allowed if path.endswith('approved') else unknown
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            r=self.client.post('/api/gmail/sync')
            self.assertEqual(r.status_code,200,r.text)
            self.assertTrue(r.json()['has_more'])
            self.assertNotIn(('messages/unknown',{'format':'full'}),calls)
            r=self.client.post('/api/gmail/sync')
            self.assertEqual(r.json()['staged'],0)
        self.assertEqual(gmail.settings()['cursor'],'page2')

    def test_reconfigure_rechecks_ignored(self):
        with app.conn() as c:gmail.stage_message(c,'inbox@example.com',mail(sender='new@bank.example'),self.config['senders'])
        self.config['senders'].append('new@bank.example')
        self.client.post('/api/gmail/configure',json=self.config)
        with app.conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM gmail_intake').fetchone()[0],0)

    def test_invalid_file_rejected(self):
        item_id=self.stage()
        with app.conn() as c:item=dict(c.execute('SELECT * FROM gmail_intake WHERE id=?',(item_id,)).fetchone())
        def get(session,path,params=None):
            return {'data':base64.urlsafe_b64encode(b'<html>not a PDF</html>').decode()} if '/attachments/' in path else mail()
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            with self.assertRaises(app.HTTPException):gmail.download_item(item)

    def test_all_senders_all_history(self):
        self.config.update(all_senders=True,start_date='',senders=[])
        self.assertEqual(self.client.post('/api/gmail/configure',json=self.config).status_code,200)
        self.assertTrue(self.client.get('/api/gmail/status').json()['all_senders'])
        calls=[]
        def get(session,path,params=None):
            calls.append((path,params))
            if path=='messages':return {'messages':[{'id':'new'}]}
            return mail('new',sender='unknown@bank.example')
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            self.assertEqual(self.client.post('/api/gmail/sync').status_code,200)
        self.assertNotIn('q',calls[0][1])
        self.assertIn(('messages/new',{'format':'full'}),calls)
        with app.conn() as c:self.assertEqual(c.execute('SELECT status FROM gmail_intake').fetchone()[0],'pending')

    def test_html_alert_and_google_security_classification(self):
        payload={'headers':[{'name':'From','value':'bank@example.com'},{'name':'Subject','value':'Account update'}],
                 'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<p>Your account was debited INR 100</p><script>ignored()</script>').decode()}}
        self.assertEqual(gmail.classify(payload,None)[2][0][3],'needs_review')
        payload['headers'][1]['value']='Security alert'
        self.assertEqual(gmail.classify(payload,None)[2][0][3],'ignored')
        payload['headers'][1]['value']='Welcome'
        payload['body']['data']=base64.urlsafe_b64encode(b'<p>Welcome to your Google account</p>').decode()
        self.assertEqual(gmail.classify(payload,None)[2][0][3],'ignored')

    def test_sender_filter_still_required_in_restricted_mode(self):
        self.config.update(senders=[],all_senders=False,start_date='')
        self.assertEqual(self.client.post('/api/gmail/configure',json=self.config).status_code,400)

    def test_indusind_alert_preview_amount_not_limit(self):
        text='The transaction on your IndusInd Bank Credit Card ending 1234 for INR 211.00 on 12-09-2026 08:59:22 pm at Upi Icici is Approved. Available Limit: INR 32,905.54.'
        payload={'headers':[{'name':'From','value':'transactionalert@indusind.com'}], 'mimeType':'text/html',
                 'body':{'data':base64.urlsafe_b64encode(('<p>'+text+'</p>').encode()).decode()}}
        r=gmail.parse_indusind_alert(payload)
        self.assertEqual(r['amount'],-211)
        self.assertEqual(r['time'],'20:59:22')
        self.assertEqual(r['date'],'2026-09-12')
        self.assertEqual(r['description'],'Upi Icici')
        self.assertFalse(r['posted'])
        for invalid in (text.replace('Approved','Declined'),text.replace('211.00','0.00'),text.replace('12-09-2026','99-09-2026')):
            payload['body']['data']=base64.urlsafe_b64encode(invalid.encode()).decode()
            with self.assertRaises(app.HTTPException):gmail.parse_indusind_alert(payload)

    def oauth_callback(self, mailbox, denied=False):
        flow=MagicMock()
        flow.credentials.refresh_token='synthetic-refresh-token'
        flow.credentials.granted_scopes=[gmail.SCOPE]
        flow.authorization_url.side_effect=lambda **kw: ('https://accounts.google.com/o/oauth2/auth?'+urlencode({'state':kw['state'],'redirect_uri':flow.redirect_uri}),kw['state'])
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_config',return_value=flow) as factory,patch('google.auth.transport.requests.AuthorizedSession',return_value=MagicMock()),patch.object(gmail,'get_json',return_value={'emailAddress':mailbox}):
            r=self.client.post('/api/gmail/connect')
            self.assertEqual(r.status_code,200,r.text)
            args=parse_qs(urlsplit(r.json()['authorization_url']).query)
            callback=args['redirect_uri'][0]
            try:
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    urllib.request.urlopen(callback+'?state=wrong&code=test',timeout=3)
                self.assertEqual(invalid.exception.code,400)
                values={'state':args['state'][0],('error' if denied else 'code'):('access_denied' if denied else 'synthetic-code')}
                with urllib.request.urlopen(callback+'?'+urlencode(values),timeout=3) as response:
                    self.assertEqual(response.status,200)
                self.assertTrue(gmail.operation_lock.acquire(timeout=3))
                gmail.operation_lock.release()
                self.assertTrue(factory.call_args.kwargs['autogenerate_code_verifier'])
                return gmail.oauth_status
            finally:
                # A valid callback terminates the local test listener; no Google traffic occurs.
                pass

    def test_oauth_state_pkce_and_refresh_token_only(self):
        self.assertEqual(self.oauth_callback('inbox@example.com'),'connected')
        token=self.vault[gmail.settings()['vault_key']+'-token']
        self.assertEqual(token,{'refresh_token':'synthetic-refresh-token'})

    def test_oauth_wrong_mailbox_rejected(self):
        self.assertEqual(self.oauth_callback('wrong@example.com'),'wrong_mailbox')
        self.assertNotIn(gmail.settings()['vault_key']+'-token',self.vault)

    def test_oauth_denial_releases_operation_lock(self):
        self.assertEqual(self.oauth_callback('inbox@example.com',denied=True),'failed')
        self.assertFalse(gmail.operation_lock.locked())


if __name__=='__main__':unittest.main()
