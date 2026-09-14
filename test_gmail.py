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

    def test_statement_rules_route_pending_without_posting(self):
        item_id=self.stage()
        rule={'name':'Card monthly','sender':'STATEMENTS@BANK.EXAMPLE','subject_keyword':'STATEMENT','filename_keyword':'.pdf','account_id':3,'password_account_id':3}
        result=self.client.post('/api/gmail/statement-rules',json=rule)
        self.assertEqual(result.status_code,200)
        route=self.client.get('/api/gmail/items').json()[0]['routing']
        self.assertEqual(route['account_id'],3);self.assertEqual(route['password_account_id'],3)
        self.assertEqual(app.bootstrap()['transactions'],[])
        # Pending items already collected are affected immediately; no mailbox sync is needed.
        rule['id']=result.json()['id'];rule['subject_keyword']='not a match'
        self.client.post('/api/gmail/statement-rules',json=rule)
        self.assertIsNone(self.client.get('/api/gmail/items').json()[0]['routing'])
        rule['subject_keyword']='statement';self.client.post('/api/gmail/statement-rules',json=rule)
        rule.pop('id');self.client.post('/api/gmail/statement-rules',json=rule)
        self.assertTrue(self.client.get('/api/gmail/items').json()[0]['routing']['ambiguous'])
        for r in self.client.get('/api/gmail/statement-rules').json(): self.client.delete('/api/gmail/statement-rules/'+str(r['id']))
        self.assertIsNone(self.client.get('/api/gmail/items').json()[0]['routing'])

    def test_statement_rules_validate_and_do_not_bypass_filtering(self):
        rule={'name':'Bank','sender':'statements@bank.example','subject_keyword':'statement','account_id':3}
        self.assertEqual(self.client.post('/api/gmail/statement-rules',json={**rule,'subject_keyword':''}).status_code,400)
        self.assertEqual(self.client.post('/api/gmail/statement-rules',json={**rule,'account_id':999}).status_code,400)
        self.client.post('/api/gmail/statement-rules',json=rule)
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',mail(),[])
        self.assertIsNone(self.client.get('/api/gmail/items').json()[0]['routing'])
        with app.conn() as c:
            c.execute("DELETE FROM gmail_intake")
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',mail(sender='statements@bank.example.evil.test'),None)
        self.assertIsNone(self.client.get('/api/gmail/items').json()[0]['routing'])

    def test_statement_rule_change_invalidates_preview_and_survives_restart(self):
        self.stage()
        with app.conn() as c: c.execute("UPDATE gmail_intake SET preview_options='old choices'")
        r=self.client.post('/api/gmail/statement-rules',json={'name':'Bank','sender':'statements@bank.example','filename_keyword':'statement','account_id':3,'password_account_id':3})
        self.assertEqual(r.status_code,200)
        self.assertIsNone(self.client.get('/api/gmail/items').json()[0]['preview_options'])
        app.init_db()
        self.assertEqual(len(self.client.get('/api/gmail/statement-rules').json()),1)
        # Empty destination-account deletion also cleans up its rules.
        self.assertEqual(self.client.delete('/api/accounts/3').status_code,200)
        self.assertEqual(self.client.get('/api/gmail/statement-rules').json(),[])

    def test_idfc_alert_parser(self):
        from parsers import parse_email
        text='Your A/C XXXXXXX1234 has been debited by INR 398.00 on 14/09/2026 00:08. New balance is INR 1,01,820.09CR.'
        result=parse_email('transaction.alerts@idfcfirstbank.com','Transaction alert',text+' '+text)
        self.assertEqual(result['amount'],-398);self.assertEqual(result['account_last4'],'1234')
        self.assertEqual(result['date'],'2026-09-14');self.assertIn('merchant not supplied',result['description'])
        credit=parse_email('transaction.alerts@idfcfirstbank.com','Alert',text.replace('debited','credited'))
        self.assertEqual(credit['kind'],'credit');self.assertEqual(credit['amount'],398)
        for body in (text.replace('398.00','0.00'),text.replace('14/09/2026','99/09/2026'),text+' '+text.replace('398.00','500.00')):
            with self.assertRaises(ValueError):parse_email('transaction.alerts@idfcfirstbank.com','Alert',body)
        with self.assertRaises(ValueError):parse_email('transaction.alerts@idfcfirstbank.com.evil.test','Alert',text)

    def prepare_alert(self):
        from parsers import parse_email
        p=parse_email('transaction.alerts@idfcfirstbank.com','Alert','Your A/C XXXXXXX1234 has been debited by INR 398.00 on 14/09/2026 00:08.')
        with app.conn() as c:
            gmail.stage_message(c,'inbox@example.com',mail(pdf=False,text='Transaction debited'),self.config['senders'])
            item=c.execute('SELECT id FROM gmail_intake').fetchone()[0]
        return item,p

    def test_alert_confirm_and_later_statement_overlap(self):
        item,p=self.prepare_alert()
        self.assertEqual(self.client.post(f'/api/gmail/items/{item}/alert-confirm',json={}).status_code,409)
        with patch.object(gmail,'read_alert',return_value=p):
            preview=self.client.post(f'/api/gmail/items/{item}/alert-preview',json={'account_id':1}).json()
        body={**preview,'category_id':preview['category_id'],'account_id':1}
        result=self.client.post(f'/api/gmail/items/{item}/alert-confirm',json=body)
        self.assertEqual(result.status_code,200,result.text);self.assertFalse(result.json()['review'])
        self.assertTrue(self.client.post(f'/api/gmail/items/{item}/alert-confirm',json=body).json()['already_imported'])
        tx=app.bootstrap()['transactions'];self.assertEqual(len(tx),1);self.assertEqual(tx[0]['source_type'],'email')
        statement=self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',b'Date,Description,Amount\n2026-09-15,Actual merchant,-398\n','text/csv')}).json()
        self.assertEqual(statement['review'],1)
        self.assertEqual(app.bootstrap()['review'][0]['duplicate_of'],tx[0]['id'])
        self.client.post('/api/imports/'+str(result.json()['import_id'])+'/undo')
        self.assertEqual(self.client.get('/api/gmail/items').json()[0]['status'],'needs_review')

    def test_alert_overlap_and_account_change_guard(self):
        self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',b'Date,Description,Amount\n2026-09-14,Existing merchant,-398\n','text/csv')})
        item,p=self.prepare_alert()
        with patch.object(gmail,'read_alert',return_value=p):
            preview=self.client.post(f'/api/gmail/items/{item}/alert-preview',json={'account_id':1}).json()
        self.assertEqual(len(preview['matches']),1)
        body={**preview,'category_id':preview['category_id'],'account_id':2}
        self.assertEqual(self.client.post(f'/api/gmail/items/{item}/alert-confirm',json=body).status_code,409)
        body['account_id']=1
        result=self.client.post(f'/api/gmail/items/{item}/alert-confirm',json=body)
        self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['review'])
        self.assertEqual(len(app.bootstrap()['transactions']),1)
        self.assertEqual(len(app.bootstrap()['review']),1)

    def test_sync_auto_adds_confirmed_accounts_and_skips_retries(self):
        sender='transaction.alerts@idfcfirstbank.com'
        self.config['senders']=[sender];self.client.post('/api/gmail/configure',json=self.config)
        with app.conn() as c:
            c.execute("INSERT INTO email_account_links VALUES('idfc','bank','1234',1)")
        alert=mail('auto1',sender=sender,pdf=False,text='Your A/C XXXXXXX1234 has been debited by INR 398.00 on 14/09/2026 00:08.')
        def get(session,path,params=None): return {'messages':[{'id':'auto1'}]} if path=='messages' else alert
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            first=self.client.post('/api/gmail/sync').json()
            self.assertEqual(first['added'],1)
            self.assertEqual(self.client.post('/api/gmail/sync').json()['added'],0)
        tx=app.bootstrap()['transactions'];self.assertEqual(len(tx),1);self.assertEqual(tx[0]['amount'],-398)
        self.assertIn('merchant not supplied',tx[0]['description'])
        self.client.post('/api/imports/'+str(tx[0]['import_id'])+'/undo')
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            self.assertEqual(self.client.post('/api/gmail/sync').json()['added'],0)
        self.assertEqual(app.bootstrap()['transactions'],[])

    def test_sync_unknown_account_then_duplicate_backlog(self):
        sender='transaction.alerts@idfcfirstbank.com'
        self.config['senders']=[sender];self.client.post('/api/gmail/configure',json=self.config)
        alert=mail('auto2',sender=sender,pdf=False,text='Your A/C XXXXXXX1234 has been debited by INR 398.00 on 14/09/2026 00:08.')
        def get(session,path,params=None): return {'messages':[{'id':'auto2'}]} if path=='messages' else alert
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=get):
            first=self.client.post('/api/gmail/sync').json();self.assertEqual(first['review'],1);self.assertEqual(first['added'],0)
        self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',b'Date,Description,Amount\n2026-09-14,Shop,-398\n','text/csv')})
        with app.conn() as c: c.execute("INSERT INTO email_account_links VALUES('idfc','bank','1234',1)")
        def backlog(session,path,params=None): return {'messages':[]} if path=='messages' else alert
        with patch.object(gmail,'google_client',return_value=MagicMock()),patch.object(gmail,'get_json',side_effect=backlog):
            r=self.client.post('/api/gmail/sync').json();self.assertEqual(r['review'],1);self.assertEqual(r['added'],0)
        self.assertEqual(len(app.bootstrap()['review']),1);self.assertEqual(len(app.bootstrap()['transactions']),1)

    def test_manual_reconciliation_preserves_edits_and_undo(self):
        item,p=self.prepare_alert()
        with patch.object(gmail,'read_alert',return_value=p):
            preview=self.client.post(f'/api/gmail/items/{item}/alert-preview',json={'account_id':1}).json()
        added=self.client.post(f'/api/gmail/items/{item}/alert-confirm',json={**preview,'account_id':1,'category_id':preview['category_id']}).json()
        tx=app.bootstrap()['transactions'][0]
        category=next(c['id'] for c in app.bootstrap()['categories'] if c['name']=='People')
        self.client.put('/api/transactions/'+str(tx['id']),json={**tx,'category_id':category})
        statement=self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',b'Date,Description,Amount\n2026-09-15,Actual merchant,-398\n','text/csv')}).json()
        candidate=app.bootstrap()['review'][0]
        result=self.client.post(f"/api/transactions/{candidate['id']}/reconcile/{tx['id']}")
        self.assertEqual(result.status_code,200,result.text)
        after=app.bootstrap()['transactions'][0]
        self.assertEqual(after['id'],tx['id']);self.assertEqual(after['description'],'Actual merchant');self.assertEqual(after['category_id'],category)
        self.assertEqual(after['source_type'],'statement');self.assertEqual(len(app.bootstrap()['transactions']),1)
        self.assertEqual(self.client.post('/api/imports/'+str(added['import_id'])+'/undo').status_code,409)
        self.assertEqual(self.client.post('/api/imports/'+str(statement['import_id'])+'/undo').status_code,200)
        restored=app.bootstrap()['transactions'][0];self.assertEqual(restored['source_type'],'email');self.assertEqual(restored['description'],tx['description'])

    def test_strong_statement_match_reconciles_without_new_row(self):
        item,p=self.prepare_alert();p['description']='Shop reference 123456789012'
        with patch.object(gmail,'read_alert',return_value=p):
            preview=self.client.post(f'/api/gmail/items/{item}/alert-preview',json={'account_id':1}).json()
        self.client.post(f'/api/gmail/items/{item}/alert-confirm',json={**preview,'account_id':1,'category_id':preview['category_id']})
        csv=b'Date,Description,Amount\n2026-09-15,Shop settled 123456789012,-398\n'
        trial=self.client.post('/api/import',data={'account_id':1,'preview':True},files={'file':('test.csv',csv,'text/csv')}).json()
        self.assertEqual(trial['reconciled'],1);self.assertEqual(app.bootstrap()['transactions'][0]['source_type'],'email')
        result=self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',csv,'text/csv')}).json()
        self.assertEqual(result['reconciled'],1);self.assertEqual(result['created'],0);self.assertEqual(result['review'],0)
        self.assertEqual(len(app.bootstrap()['transactions']),1)
        tx=app.bootstrap()['transactions'][0]
        self.client.put('/api/transactions/'+str(tx['id']),json={**tx,'description':'My edited merchant'})
        self.assertEqual(self.client.post('/api/imports/'+str(result['import_id'])+'/undo').status_code,409)
        repeated=self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',csv,'text/csv')}).json()
        self.assertEqual(repeated['review'],1)

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
