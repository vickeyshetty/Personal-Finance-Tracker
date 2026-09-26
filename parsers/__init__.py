"""Trusted, explicitly registered parser modules. Never load code from uploads."""
from . import idfc_alert, indusind_alert, hdfc_alert, hdfc_bank_alert

PARSERS = (idfc_alert, indusind_alert, hdfc_alert, hdfc_bank_alert)

def catalog():
    return [p.INFO for p in PARSERS]

def parse_email(sender, subject, text):
    matches=[p for p in PARSERS if sender.lower() in p.INFO['senders']]
    results=[]
    for parser in matches:
        try: result=parser.parse(text)
        except (ValueError,ArithmeticError): continue
        results.append(dict(result,parser_id=parser.INFO['id'],parser_version=parser.INFO['version'],provisional=True,posted=False,currency='INR'))
    if len(results)!=1:
        raise ValueError('No single supported transaction-email parser matched this sender and format.')
    return results[0]
