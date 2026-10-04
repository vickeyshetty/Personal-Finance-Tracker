"""IDFC consolidated savings-account PDFs, with mandatory reconciliation checks."""
import re
from datetime import datetime
from decimal import Decimal

MONEY = r'[\d,]+\.\d{2}'
HEADER = ['Date and Time', 'Value Date', 'Transaction Details', 'Ref/Cheque No.',
          'Withdrawals (INR)', 'Deposits (INR)', 'Balance (INR)']


def clean(value):
    return ' '.join((value or '').split())


def description_from_chars(chars, right_edge):
    """Remove only hard word wraps, using glyph widths and the column boundary.

    PDF extraction loses the distinction between spaces and line wrapping. A
    word split at the margin cannot fit as one token in the column; ordinary
    word wrapping can. Both tests matter (e.g. ENTRY / CBX must stay separate).
    """
    if not chars:
        return None
    lines = []
    for ch in sorted(chars, key=lambda c: (c['top'], c['x0'])):
        if not lines or abs(ch['top'] - lines[-1][0]['top']) > 2:
            lines.append([])
        lines[-1].append(ch)
    lines = [sorted(line, key=lambda c: c['x0']) for line in lines]
    left_edge = min(c['x0'] for line in lines for c in line)
    # The observed table has a small inset on both sides of each cell.
    usable_width = right_edge - left_edge - 2
    output = ''.join(c['text'] for c in lines[0])
    for previous, following in zip(lines, lines[1:]):
        a = ''.join(c['text'] for c in previous)
        b = ''.join(c['text'] for c in following)
        last = re.search(r'\S+$', a)
        first = re.match(r'\S+', b)
        join = False
        if last and first:
            tail = previous[last.start():]
            head = following[:first.end()]
            width = sum(c['x1']-c['x0'] for c in tail + head)
            remaining = right_edge - previous[-1]['x1'] - 2
            join = width > usable_width and remaining < following[0]['x1']-following[0]['x0']
        output += ('' if join or a.endswith(' ') or b.startswith(' ') else ' ') + b
    return clean(output)


def matches(text):
    return 'CONSOLIDATED STATEMENT' in text and 'IDFC FIRST BANK' in text.upper() and 'SAVINGS ACCOUNT DETAILS FOR A/C' in text


def account_number(text):
    numbers = re.findall(r'SAVINGS ACCOUNT DETAILS FOR A/C\s*:\s*(\d{8,20})', text)
    if len(numbers) != 1 or re.search(r'CURRENT ACCOUNT DETAILS FOR A/C',text,re.I):
        raise ValueError('IDFC PDF must contain exactly one savings account. Split multi-account statements before importing.')
    return numbers[0]


def money(value, balance=False):
    pattern = f'({MONEY})' + (r'\s+(CR|DR)' if balance else '')
    m = re.fullmatch(pattern, clean(value), re.I)
    if not m:
        raise ValueError('Unreadable IDFC amount; no transactions imported.')
    result = Decimal(m[1].replace(',', ''))
    return -result if balance and m[2].upper() == 'DR' else result


def parse_tables(text, tables):
    account_number(text)
    period = re.search(r'STATEMENT PERIOD\s*:\s*(\d{2}-[A-Z]{3}-\d{4}) to (\d{2}-[A-Z]{3}-\d{4})', text, re.I)
    summary = re.search(rf'^({MONEY}\s+(?:CR|DR))\s+(\d+)\s+(\d+)\s+({MONEY})\s+({MONEY})\s+({MONEY}\s+(?:CR|DR))\s*$', text, re.M | re.I)
    if not period or not summary:
        raise ValueError('IDFC statement period or account totals could not be verified.')
    start, end = [datetime.strptime(x, '%d-%b-%Y').date() for x in period.groups()]
    opening, debit_count, credit_count, debits, credits, closing = summary.groups()
    running = money(opening, True)
    rows = []
    opening_seen = False
    for table in tables:
        if not table or [clean(v) for v in table[0]] != HEADER:
            raise ValueError('Unsupported IDFC transaction table header.')
        for cells in table[1:]:
            if len(cells) != 7 or any(v is None for v in cells):
                raise ValueError('Incomplete IDFC transaction row.')
            day, value_date, description, reference, debit, credit, balance = map(clean, cells)
            if description.lower() == 'opening balance':
                if rows or opening_seen or day or debit or credit or money(balance, True) != running:
                    raise ValueError('IDFC opening balance does not match the summary.')
                opening_seen = True
                continue
            stamp = datetime.strptime(day, '%d %b %y %H:%M')
            datetime.strptime(value_date, '%d %b %y')
            if not start <= stamp.date() <= end or not description or bool(debit) == bool(credit):
                raise ValueError('Ambiguous IDFC transaction date, description, or debit/credit direction.')
            amount = -money(debit) if debit else money(credit)
            if not amount:
                raise ValueError('Zero-valued IDFC transaction requires review.')
            running += amount
            if running != money(balance, True):
                raise ValueError('IDFC running balance mismatch; a row may be missing or unreadable.')
            rows.append(dict(Date=stamp.date().isoformat(), Time=stamp.strftime('%H:%M:%S'), Description=description + (f' · Ref {reference}' if reference else ''), Amount=float(amount)))
    actual_debits = sum((Decimal(str(-r['Amount'])) for r in rows if r['Amount'] < 0), Decimal(0))
    actual_credits = sum((Decimal(str(r['Amount'])) for r in rows if r['Amount'] > 0), Decimal(0))
    if (not opening_seen or not rows or sum(r['Amount'] < 0 for r in rows) != int(debit_count)
            or sum(r['Amount'] > 0 for r in rows) != int(credit_count)
            or actual_debits != money(debits) or actual_credits != money(credits)
            or running != money(closing, True)):
        raise ValueError('IDFC extracted transactions do not match statement counts, totals, or closing balance.')
    return rows


def parse_document(document):
    texts = [p.extract_text() or '' for p in document.pages]
    text = '\n'.join(texts)
    if not matches(texts[0]):
        raise ValueError('Not a supported IDFC savings statement.')
    tables = []
    for page, page_text in zip(document.pages, texts):
        if 'Date and Time Value Date Transaction Details' not in page_text:
            continue
        words = page.extract_words()
        header = next((w for i,w in enumerate(words) if [v['text'] for v in words[i:i+3]] == ['Date','and','Time']), None)
        if not header:
            raise ValueError('IDFC transaction header could not be located.')
        # Crop away the artwork above the first table: its borders interfere with
        # pdfplumber's line detection and can otherwise hide the date column.
        candidates = page.crop((0, header['top'] - 3, page.width, page.height)).find_tables()
        found = [(t, t.extract()) for t in candidates]
        found = [(t, data) for t, data in found if data and [clean(v) for v in data[0]] == HEADER]
        if len(found) != 1:
            raise ValueError('IDFC transaction columns could not be read safely.')
        table, data = found[0]
        for row, cells in zip(table.rows[1:], data[1:]):
            box = row.cells[2]
            if box is not None:
                description = description_from_chars(page.crop(box).chars, box[2])
                if description is not None:
                    cells[2] = description
        tables.append(data)
    return parse_tables(text, tables)
