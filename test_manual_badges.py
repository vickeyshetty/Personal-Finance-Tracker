import unittest
from test_app import LedgerTests
import app

class ManualBadgeTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self)
        self.client.post('/api/import',data={'account_id':1},files={'file':('t.csv',b'Date,Description,Amount\n2026-08-01,Shop,-100\n2026-08-02,UPI shop,-200\n','text/csv')})
        self.tx=app.bootstrap()['transactions']
        self.ids=[t['id'] for t in self.tx]
        self.badge=self.client.get('/api/badges').json()[0]['id']
    def tearDown(self):LedgerTests.tearDown(self)
    def bulk(self,action,ids=None,badges=None):
        return self.client.post('/api/transaction-badges/bulk',json={'transaction_ids':self.ids if ids is None else ids,'badge_ids':[self.badge] if badges is None else badges,'action':action})
    def test_bulk_add_remove_auto_and_persistence(self):
        for action,value in [('add',True),('remove',False),('auto',None)]:
            self.assertEqual(self.bulk(action).status_code,200)
            app.init_db()
            for t in app.bootstrap()['transactions']:
                self.assertEqual(t['badge_overrides'].get(str(self.badge)),value)
                self.assertEqual(t['amount'],next(x['amount'] for x in self.tx if x['id']==t['id']))
    def test_atomic_validation(self):
        self.assertEqual(self.bulk('add',ids=self.ids+[99999]).status_code,400)
        self.assertTrue(all(not t['badge_overrides'] for t in app.bootstrap()['transactions']))
        self.assertEqual(self.bulk('add',badges=[99999]).status_code,400)
        self.assertEqual(self.bulk('replace').status_code,400)
    def test_edit_and_delete_badge(self):
        t=self.tx[0]
        r=self.client.put('/api/transactions/'+str(t['id']),json={**t,'badge_overrides':{str(self.badge):True}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(app.tx_rows('t.id=?',(t['id'],))[0]['badge_overrides'][str(self.badge)])
        # A normal transaction edit that omits badge choices must preserve them.
        body={k:v for k,v in t.items() if k!='badge_overrides'}
        self.assertEqual(self.client.put('/api/transactions/'+str(t['id']),json=body).status_code,200)
        self.assertTrue(app.tx_rows('t.id=?',(t['id'],))[0]['badge_overrides'])
        self.client.delete('/api/badges/'+str(self.badge))
        self.assertFalse(app.tx_rows('t.id=?',(t['id'],))[0]['badge_overrides'])
    def test_manual_only_and_subscriptions_category(self):
        self.assertEqual(self.client.post('/api/badges',data={'name':'Manual only'}).status_code,200)
        self.assertEqual(next(b for b in self.client.get('/api/badges').json() if b['name']=='Manual only')['patterns'],[])
        self.assertIn('Subscriptions',[c['name'] for c in app.bootstrap()['categories']])
    def test_excluded_allowed_trash_rejected(self):
        self.client.post('/api/transactions/'+str(self.ids[0])+'/mark-transfer')
        self.assertEqual(self.bulk('add').status_code,200)
        self.client.post('/api/transactions/'+str(self.ids[0])+'/delete')
        self.assertEqual(self.bulk('remove').status_code,400)

if __name__=='__main__':unittest.main()
