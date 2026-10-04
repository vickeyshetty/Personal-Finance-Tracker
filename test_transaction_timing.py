import sqlite3
import unittest
import transaction_timing as timing


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.row_factory = sqlite3.Row
        self.c.execute('CREATE TABLE gmail_intake(import_id,received,filename)')
        timing.init_schema(self.c)

    def tearDown(self):
        self.c.close()

    def test_order_and_statement_receipt_exclusion(self):
        self.c.executemany('INSERT INTO gmail_intake VALUES(?,?,?)', [
            (1, '2026-09-01T09:00:00+00:00', ''),
            (2, '2026-09-01T10:00:00+00:00', ''),
            (3, '2026-09-01T22:00:00+00:00', 'statement.pdf')])
        timing.save(self.c, 2, dict(date='2026-09-01', time='13:00:00'))
        items = [dict(id=i, import_id=i, date='2026-09-01', amount=-10,
                      source_type='statement') for i in range(1, 5)]
        result = timing.annotate(items, self.c)
        self.assertEqual([r['id'] for r in result], [1, 2, 4, 3])
        self.assertEqual(result[0]['time_label'], '≈ 14:30 IST · email received')
        self.assertEqual(result[1]['time_source'], 'transaction')
        self.assertEqual(result[-1]['time_source'], None)
        self.assertEqual(sum(r['amount'] for r in result), -40)

    def test_placeholder_invalid_and_real_midnight(self):
        for i, extra in enumerate([{'parser_id':'hdfc.bank-alert'},
                                   {'parser_version':'custom-1'}, {}], 1):
            timing.save(self.c, i, dict(date='2026-09-01', time='00:00:00', **extra))
        timing.save(self.c, 4, dict(date='2026-09-01', time='invalid'))
        self.assertEqual([r[0] for r in self.c.execute('SELECT import_id FROM alert_times')], [3])

    def test_dates_remain_primary_and_bad_receipts_are_unknown(self):
        self.c.executemany('INSERT INTO gmail_intake VALUES(?,?,?)', [
            (1, '2026-09-02T00:00:00+00:00', ''), (2, 'bad', '')])
        items = [dict(id=1, import_id=1, date='2026-09-01'),
                 dict(id=2, import_id=2, date='2026-09-02')]
        result = timing.annotate(items, self.c)
        self.assertEqual([r['id'] for r in result], [2, 1])
        self.assertIn('02 Sep 2026', result[1]['time_label'])
        self.assertEqual(result[1]['date'], '2026-09-01')


if __name__ == '__main__':
    unittest.main()
