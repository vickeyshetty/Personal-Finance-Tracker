"""Display-only within-day ordering; never used for deduplication or totals."""
from datetime import datetime, timedelta, timezone
import re

IST = timezone(timedelta(hours=5, minutes=30))


def statement_clock(value, numeric=False):
    """Optional clock from a time column or date/time value; never invent midnight."""
    if isinstance(value, datetime):
        return value.strftime('%H:%M:%S')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        fraction = value % 1
        if not numeric and fraction == 0:
            return None
        seconds = round(fraction * 86400) % 86400
        return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'
    match = re.search(r'(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)?(?!\w)', str(value or ''), re.I)
    if not match:
        return None
    clock, meridiem = match.groups()
    fmt = '%I:%M' if meridiem else '%H:%M'
    if clock.count(':') == 2: fmt += ':%S'
    try:
        return datetime.strptime(clock + (meridiem.upper() if meridiem else ''), fmt + ('%p' if meridiem else '')).strftime('%H:%M:%S')
    except ValueError:
        return None


def init_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS alert_times (
        import_id INTEGER PRIMARY KEY, transaction_date TEXT NOT NULL,
        transaction_time TEXT NOT NULL)''')


def save(c, import_id, parsed):
    clock = parsed.get('time')
    # This parser explicitly supplies a midnight placeholder, not an actual time.
    if parsed.get('parser_id') == 'hdfc.bank-alert' or parsed.get('parser_version') == 'custom-1' or not clock:
        return
    try:
        clock = datetime.strptime(clock, '%H:%M:%S').strftime('%H:%M:%S')
    except (ValueError, TypeError):
        return
    c.execute('INSERT OR REPLACE INTO alert_times VALUES(?,?,?)',
              (import_id, parsed['date'], clock))


def annotate(items, c):
    # Only single-transaction alerts: never borrow receipt times from PDF emails.
    receipts = {r['import_id']: r['received'] for r in c.execute('''
        SELECT import_id, MIN(received) received FROM gmail_intake
        WHERE filename='' AND import_id IS NOT NULL GROUP BY import_id''')}
    actual = {r['import_id']: dict(r) for r in c.execute('SELECT * FROM alert_times')}
    for t in items:
        t.update(sort_seconds=-1, time_label='', time_source=None)
        stamp = actual.get(t['import_id'])
        if t.get('statement_time') and t.get('statement_time_date') == t['date']:
            clock = datetime.strptime(t['statement_time'], '%H:%M:%S')
            t.update(time_label=clock.strftime('%H:%M') + ' IST · statement', time_source='statement')
        elif stamp and stamp['transaction_date'] == t['date']:
            clock = datetime.strptime(stamp['transaction_time'], '%H:%M:%S')
            t.update(time_label=clock.strftime('%H:%M') + ' IST', time_source='transaction')
        else:
            try:
                received = datetime.fromisoformat(receipts.get(t['import_id'], ''))
                if received.tzinfo is None or received.year < 2000:
                    continue
                clock = received.astimezone(IST)
            except (ValueError, TypeError):
                continue
            label = clock.strftime('%H:%M')
            if clock.date().isoformat() != t['date']:
                label = clock.strftime('%d %b %Y %H:%M')
            t.update(time_label='≈ ' + label + ' IST · email received', time_source='email_received')
        t['sort_seconds'] = clock.hour * 3600 + clock.minute * 60 + clock.second
    items.sort(key=lambda t: (t['date'], t['sort_seconds'], t['id']), reverse=True)
    return items
