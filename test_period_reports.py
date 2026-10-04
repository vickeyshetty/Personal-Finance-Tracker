import unittest
from test_salary_cycles import SalaryCycleTests
import app
import period_reports


class PeriodReportTests(unittest.TestCase):
    def setUp(self):
        SalaryCycleTests.setUp(self)

    def tearDown(self):
        SalaryCycleTests.tearDown(self)

    def test_report_uses_one_ledger_snapshot_and_never_stale_cache(self):
        from unittest.mock import patch
        first=self.client.post('/api/salary-cycles',json={'start':'2026-08-31'}).json()['id']
        for params in ({'month':'2026-09'},{'cycle_id':first}):
            with patch.object(app,'tx_rows',wraps=app.tx_rows) as read:
                response=self.client.get('/api/period-report',params=params)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(read.call_count,1)
        before=self.client.get('/api/period-report?month=2026-09').json()['spent']
        with app.conn() as c:c.execute("UPDATE transactions SET amount=amount-10 WHERE description='Shop'")
        after=self.client.get('/api/period-report?month=2026-09').json()['spent']
        self.assertEqual(after,before+10)

    def test_same_boundaries_same_contract(self):
        # A date-only cycle starting on the first has exactly the same report as the month.
        result=self.client.post('/api/salary-cycles',json={'start':'2026-09-01'})
        self.assertEqual(result.status_code,200)
        cycle=self.client.get('/api/period-report',params={'cycle_id':result.json()['id']}).json()
        month=self.client.get('/api/period-report',params={'month':'2026-09'}).json()
        for key in ('salary','spent','gross','refunds','investments','remaining','categories','transactions','food','merchants','cash_flow'):
            self.assertEqual(cycle[key],month[key],key)

    def test_boundaries_and_accounting(self):
        salary=next(t['id'] for t in self.candidates if t['description']=='Payday')
        first=self.client.post('/api/salary-cycles',json={'start':'2026-08-31','salary_id':salary}).json()['id']
        self.client.post('/api/salary-cycles',json={'start':'2026-09-25'})
        result=self.client.get('/api/period-report',params={'cycle_id':first})
        self.assertEqual(result.status_code,200,result.text)
        r=result.json()
        self.assertEqual((r['salary'],r['spent'],r['investments'],r['remaining']),(10000,900,2000,7100))
        self.assertEqual(r['end'],'2026-09-24')
        self.assertNotIn('Investments',[g['category'] for g in r['categories']])
        self.assertNotIn('Next cycle shop',[t['description'] for t in r['transactions']])
        self.assertTrue(any(g['category']=='Card repayments' for g in r['cash_flow']['outflows']))

    def test_missing_salary_review_and_trash(self):
        with app.conn() as c:
            c.execute("UPDATE transactions SET status='review' WHERE description='Shop'")
            c.execute("UPDATE transactions SET status='deleted' WHERE description='Invest'")
        r=period_reports.summarize(app,'2026-09-01','2026-09-24')
        self.assertIsNone(r['salary']);self.assertIsNone(r['remaining'])
        self.assertEqual(r['review_count'],1);self.assertEqual(r['investments'],0)
        self.assertEqual(r['spent'],-100)

    def test_validation(self):
        self.assertEqual(self.client.get('/api/period-report?month=bad').status_code,400)
        self.assertEqual(self.client.get('/api/period-report?month=2099-01').status_code,400)
        self.assertEqual(self.client.get('/api/period-report?month=0001-01').status_code,400)
        self.assertEqual(self.client.get('/api/period-report?cycle_id=999').status_code,400)

    def test_chart_does_not_shift_when_another_bar_is_selected(self):
        from datetime import date
        month=self.client.get('/api/period-report',params={'month':date.today().strftime('%Y-%m')}).json()
        previous=self.client.get('/api/period-report',params={'month':month['trend'][-2]['key']}).json()
        self.assertEqual(month['trend'],previous['trend'])
        first=self.client.post('/api/salary-cycles',json={'start':'2026-08-31','salary_id':next(t['id'] for t in self.candidates if t['description']=='Payday')}).json()['id']
        a=self.client.get('/api/period-report',params={'cycle_id':first}).json()
        b=self.client.get('/api/period-report',params={'cycle_id':'auto-2026-09'}).json()
        self.assertEqual(a['trend'],b['trend'])
        self.assertNotEqual(a['start'],b['start'])
        self.assertNotEqual(a['salary'],b['salary'])

if __name__=='__main__': unittest.main()
