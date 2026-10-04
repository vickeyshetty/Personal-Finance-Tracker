import unittest
from test_app import LedgerTests
import app

class SalaryCycleTests(unittest.TestCase):
    def setUp(self):
        LedgerTests.setUp(self);self.client.headers['X-Ledger-Token']=app.LOCAL_TOKEN
        content=b'Date,Description,Amount\n2026-08-31,Payday,10000\n2026-09-01,Shop,-1000\n2026-09-02,Refund,100\n2026-09-03,Invest,-2000\n2026-09-04,Transfer,-500\n2026-09-05,CC PAYMENT,-600\n2026-09-06,Other credit,200\n2026-09-25,Next payday,12000\n2026-09-25,Next cycle shop,-300\n'
        self.client.post('/api/import',data={'account_id':1},files={'file':('test.csv',content,'text/csv')})
        with app.conn() as c:
            salary=c.execute("SELECT id FROM categories WHERE name='Salary'").fetchone()[0]
            investment=c.execute("SELECT id FROM categories WHERE name='Investments'").fetchone()[0]
            c.execute("UPDATE transactions SET category_id=?,kind='income' WHERE description IN ('Payday','Next payday')",(salary,))
            c.execute("UPDATE transactions SET category_id=? WHERE description='Invest'",(investment,))
            c.execute("UPDATE transactions SET kind='transfer',status='excluded' WHERE description='Transfer'")
        self.candidates=self.client.get('/api/salary-cycles').json()['candidates']
    def tearDown(self):LedgerTests.tearDown(self)
    def save(self,day,salary=None):
        result=self.client.post('/api/salary-cycles',json={'start':day,'salary_id':salary})
        self.assertEqual(result.status_code,200,result.text);return result.json()['id']
    def test_closed_cycle_no_double_count(self):
        first=self.save('2026-08-31',next(t['id'] for t in self.candidates if t['description']=='Payday'))
        self.save('2026-09-25',next(t['id'] for t in self.candidates if t['description']=='Next payday'))
        self.client.post('/api/import',data={'account_id':3},files={'file':('card.csv',b'Date,Description,Amount\n2026-09-07,Card shop,-400\n2026-09-08,Payment received,600\n','text/csv')})
        r=self.client.get('/api/salary-cycles/'+str(first)).json()
        self.assertEqual(r['end'],'2026-09-24');self.assertFalse(r['open'])
        self.assertEqual((r['salary'],r['spent'],r['investments'],r['remaining']),(10000,1300,2000,6700))
        self.assertNotIn('Next cycle shop',[t['description'] for t in r['transactions']])
    def test_missing_salary_and_future_validation(self):
        first=self.save('2026-09-01')
        self.save('2026-09-25',next(t['id'] for t in self.candidates if t['description']=='Next payday'))
        r=self.client.get('/api/salary-cycles/'+str(first)).json()
        self.assertIsNone(r['salary']);self.assertIsNone(r['remaining'])
        self.assertEqual(self.client.post('/api/salary-cycles',json={'start':'2099-01-01'}).status_code,400)
    def test_explicit_confirmation_unique_and_editable(self):
        self.assertEqual(self.client.get('/api/salary-cycles').json()['cycles'],[])
        salary=self.candidates[0]['id'];first=self.save('2026-08-31',salary)
        self.assertEqual(self.client.post('/api/salary-cycles',json={'start':'2026-09-01','salary_id':salary}).status_code,400)
        self.assertEqual(self.client.post('/api/salary-cycles',json={'id':first,'start':'2026-08-30','salary_id':salary}).status_code,200)
        with app.conn() as c:c.execute("UPDATE transactions SET status='deleted' WHERE id=?",(salary,))
        self.assertFalse(self.client.get('/api/salary-cycles').json()['cycles'][0]['valid'])
        self.assertEqual(self.client.get('/api/salary-cycles/'+str(first)).status_code,400)
    def test_review_and_deleted_excluded(self):
        first=self.save('2026-08-31',self.candidates[0]['id'])
        with app.conn() as c:
            c.execute("UPDATE transactions SET status='review' WHERE description='Shop'")
            c.execute("UPDATE transactions SET status='deleted' WHERE description='Invest'")
        r=self.client.get('/api/salary-cycles/'+str(first)).json()
        self.assertEqual(r['review_count'],1);self.assertEqual(r['investments'],0)

    def test_next_month_salary_automatically_splits_cycle_without_writes(self):
        first=self.save('2026-08-31',next(t['id'] for t in self.candidates if t['description']=='Payday'))
        cycles=self.client.get('/api/salary-cycles').json()['cycles']
        automatic=next(c for c in cycles if c.get('automatic'))
        self.assertEqual(automatic['start'],'2026-09-25')
        before=self.client.get('/api/salary-cycles/'+str(first)).json()
        after=self.client.get('/api/salary-cycles/'+automatic['id']).json()
        self.assertEqual(before['end'],'2026-09-24')
        self.assertEqual((before['salary'],after['salary']),(10000,12000))
        self.assertEqual(after['spent'],300)
        self.assertEqual(len(app.rows('SELECT * FROM salary_cycles')),1)
        self.assertEqual(len({t['id'] for t in before['salary_entries']+after['salary_entries']}),2)

    def test_missing_month_uses_estimated_boundary_not_combined_months(self):
        with app.conn() as c:c.execute("UPDATE transactions SET status='deleted' WHERE description='Next payday'")
        first=self.save('2026-08-31',next(t['id'] for t in self.candidates if t['description']=='Payday'))
        cycles=self.client.get('/api/salary-cycles').json()['cycles']
        missing=next(c for c in cycles if c['id']=='auto-2026-09')
        self.assertEqual(missing['start'],'2026-09-30')
        self.assertTrue(missing['estimated'])
        self.assertEqual(self.client.get('/api/salary-cycles/'+str(first)).json()['end'],'2026-09-29')
        r=self.client.get('/api/salary-cycles/auto-2026-09').json()
        self.assertIsNone(r['salary']);self.assertIsNone(r['remaining'])

    def test_automatic_boundary_can_be_overridden(self):
        self.save('2026-08-31',next(t['id'] for t in self.candidates if t['description']=='Payday'))
        manual=self.save('2026-09-26',next(t['id'] for t in self.candidates if t['description']=='Next payday'))
        cycles=self.client.get('/api/salary-cycles').json()['cycles']
        self.assertEqual([c['id'] for c in cycles if c['start'].startswith('2026-09')],[manual])

    def test_multiple_salary_credits_in_month_do_not_split_cycle(self):
        self.save('2026-08-31',next(t['id'] for t in self.candidates if t['description']=='Payday'))
        with app.conn() as c:
            c.execute("UPDATE transactions SET category_id=(SELECT id FROM categories WHERE name='Salary'),kind='income',date='2026-09-26' WHERE description='Other credit'")
        cycles=self.client.get('/api/salary-cycles').json()['cycles']
        self.assertEqual(len([c for c in cycles if c['start'].startswith('2026-09')]),1)
        self.assertEqual(self.client.get('/api/salary-cycles/auto-2026-09').json()['salary'],12200)

if __name__=='__main__':unittest.main()
