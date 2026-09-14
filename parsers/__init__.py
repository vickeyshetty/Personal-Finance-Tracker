"""Trusted, explicitly registered parser modules. Never load code from uploads."""
from . import idfc_alert, indusind_alert, hdfc_alert

PARSERS = (idfc_alert, indusind_alert, hdfc_alert)

def catalog():
    return [p.INFO for p in PARSERS]

def parse_email(sender, subject, text):
    matches=[p for p in PARSERS if sender.lower() in p.INFO['senders']]
    if len(matches)!=1:
        raise ValueError('No supported transaction-email parser for this sender yet.')
    result=matches[0].parse(text)
    return dict(result,parser_id=matches[0].INFO['id'],parser_version=matches[0].INFO['version'],provisional=True,posted=False,currency='INR')
