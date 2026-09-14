# Parser modules

The first plugin-style boundary covers transaction emails. PDF/spreadsheet parsers remain in app.py for now; migrating them is separate work.

Each trusted module exports INFO (stable id, version, display name, exact senders and account type) and parse(text). The registry explicitly imports modules; no dynamic imports, uploaded Python, downloaded plugins or eval are used. A developer adds a module, registers it in parsers/__init__.py and adds synthetic tests, then restarts the app. Code changes should be reviewed on develop before release.

parse receives inert plain text after MIME/HTML decoding. It returns date (ISO), time, signed amount, description, kind, issuer, account_type, account_last4 and an explanatory note. It must identify exactly one transaction, distinguish amounts from balances, reject unsupported/ambiguous templates and never infer a merchant or purpose absent from the email. Repeated plain/HTML representations of the same entry should deduplicate inside the parser. Do not store personal email fixtures in this repository.

Parsers must not perform network requests, access credentials or write to the database. They are trusted application code, not sandboxed third-party plugins. Gmail transport handles authentication and sender eligibility; the app owns account selection, category rules, preview tokens, duplicate review, posting and undo. Passwords stay outside parsers in Windows Credential Manager.

Run `python -m unittest test_app.LedgerTests test_credentials.CredentialTests test_gmail.GmailTests test_custom_parsers.ParserTests -q` before registering a new module.

The sidebar Developer mode now opens a parser workspace for declarative definitions. `custom_parsers.py` validates, tests and dispatches these definitions for email, PDF text and table inputs; it never runs user code. Test tokens bind successful previews to the exact definition and expire after 30 minutes. Custom definitions are stored in SQLite, not the source repository. Samples and passwords are not saved with definitions. Prefer synthetic samples, and never embed secrets in literal markers or extraction patterns.
