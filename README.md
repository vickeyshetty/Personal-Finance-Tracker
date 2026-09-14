# Ledger — Personal Finance Tracker

Local, single-user statement tracking with import previews, batch undo, manual transfer pairing, refund classification and a current-calendar-month dashboard.

## Setup (Windows)

Install Python 3.11 or newer and Git. Windows is required for saved PDF passwords and Gmail credentials; manual unlocked-file imports do not use the credential vault. Node.js is optional and is used only for JavaScript syntax checks.

Clone the development version and create a virtual environment:

```powershell
git clone --branch develop git@github.com:vickeyshetty/Personal-Finance-Tracker.git
cd Personal-Finance-Tracker
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

On first startup, Ledger creates a fresh `finance.db`, default categories and a placeholder Primary bank account. No personal transactions or credentials are supplied. Open **Import & accounts** to rename/add accounts and preview your first statement. Gmail setup is optional; manual imports work without a Google Cloud project. Stop the server with Ctrl+C.

For development with automatic reload:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Keep the server local; this application does not have multi-user authentication.

## Import and recover

Select several CSV/XLS/XLSX/PDF files together in Import & accounts. Preview each destination, row list and debit/credit totals, then confirm each import. Detection recognises specific layouts; it does not guarantee identity when two accounts use the same bank/layout. Override the suggested account when needed. PDFs currently support SBI Card and CRED/IndusInd text statements, including password-protected files using saved Windows credentials (see below). Scanned PDFs are not supported.

Import history includes a **Review duplicates** link for each batch with pending duplicates. The Review page can filter by import, keeping new duplicate candidates separate from older unresolved ones. In Transactions, search/filter first, then use the table-header checkbox to select all matching current entries for bulk categorisation; Review and Trash entries are not selected.

New uploads have separate import IDs. Undo moves that batch's entries to Trash. Historical imports, which had no batch IDs, are grouped by original filename and account and labelled as historical groups. Moving a historical group affects all those uploads. Restore individual entries from Trash. Re-uploading a statement whose entries were all undone can import them again; existing active or review entries trigger duplicate review.

Statements are not automatically reconciled against printed opening/closing balances. Compare preview totals with the source. Some parsers omit non-transaction/footer rows and the skipped count is not a guarantee of complete extraction.

## Transaction meaning

The Overview opens on the current calendar month. Selecting a chart bar or using the month picker updates the main spending/refund/category cards, category donut, merchants and cash-flow panel together. **Back to current month** returns to today's month. The donut shows gross spending; refunds remain separate. Cash flow is shown first and uses bank movements only: card repayments count as bank outflows, card purchases do not count a second time, and self-transfers are excluded. Net cash movement is not a balance or a guarantee of savings. It depends on complete imports and correct classification. Investments is available as a purpose category; categorisation alone does not change transaction type or automatically exclude an expense from spending.

UPI, EMI, NEFT, IMPS and Auto-pay badges are detected from description text and are informational, not verified payment metadata. Transfer pairing is available inside **Edit → Pair / mark self-transfer** instead of a button on every row.

- Purchase / fee: counts as spending when active.
- Refund / cashback: reduces spending in the month the credit arrives, even if the purchase was in another month.
- Card repayment: excluded from spending; card-side credits appear separately as repayments received.
- Self-transfer: excluded for any amount. Select exactly one opposite entry or mark one side manually. Suggestions cover seven days; absence of a suggestion doesn't prevent marking either side.
- Unclassified card credit: visible for review, not assumed to be a refund.

Categories describe purpose; transaction type controls accounting. Use Edit to correct both. Changing a linked transfer in Edit removes the link; the opposite side remains excluded until edited separately.

The main metric is the selected month's spending after refunds, defaulting to the current calendar month. The six-month chart includes zero months and progresses oldest-to-newest from left to right. Click a month to inspect its purchases, refunds, category ranking and entries; the main spending metric updates with the selected month. Category ranking is by gross spending, with separate refund and net columns. Swiggy food orders use Online food order; Instamart and Zepto use Quick commerce. These rules apply to future imports too. People is available for manually categorising money sent to or received from people; transaction type still controls whether it affects spending. It shows imported data only, not live bank balances. Recurring suggestions require three similar amounts spaced 25–35 days apart.

## Data protection

`finance.db` contains private financial data. Startup creates one daily backup in `backups/`; Download database backup creates an additional consistent SQLite snapshot. Export CSV downloads the active/excluded ledger, not the original bank statements. These are backups/exports, not a bank synchronisation service.

To restore a full backup: stop the server, preserve the current finance.db under a different filename, copy the chosen backup to finance.db, then restart. No browser restore control is provided yet. Store another backup outside this computer. Database and backup files are excluded from Git.

Migrations run once; restarting does not recategorise or reassign existing transactions. Current and original duplicate fingerprints are retained separately. An audit table records transaction snapshots for edits, moves and deletion; audit browsing is not exposed in the UI yet.

## Categories, badges and keyword rules

Open **Categories & badges** in the sidebar. Add categories or remove unused ones. Removal requires confirmation, moves all affected entries (including Review and Trash) to Uncategorized, and removes rules targeting that category. It preserves amounts, transaction types and duplicate fingerprints; affected entries are audited. Uncategorized, Transfers, Credit Card Payment and Refund / Cashback are protected because the accounting/import logic requires them. Removed default categories stay removed after restart.

Keyword rules apply automatically to future statement imports, including Gmail statement imports. Enter one literal keyword or phrase per rule and choose its category. Matching ignores case; the longest matching phrase wins, so `swiggyinstamart` takes precedence over `swiggy`. Edit can change a rule's keyword or category. Rules do not retroactively change older transactions; bulk categorisation remains available for existing entries. Recognised repayments keep the accounting category assigned by the importer. Category rules do not change transaction types.

Add, edit or remove badges in the same page. Comma-separated keywords mean "match any"; optionally require whole-word matches. Badges are informational and can overlap (for example UPI and Auto-pay). Badge changes affect existing and future transaction displays without changing financial records. Deleted default badges are not recreated on restart.

## Automated checks

Use the virtual environment's Python (`.\.venv\Scripts\python.exe`) for these commands if it is not activated.

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest test_app test_credentials.CredentialTests test_gmail.GmailTests -v
node --check static/app.js
node --check static/gmail.js
node test_badges.js
```

Tests use temporary databases. No bank statements or real transaction fixtures are checked in.

## Monthly collection

Use a single folder for statement downloads. Continue using the tested HDFC/IDFC Excel exports and CRED/IndusInd/SBI PDFs, then select them together in Ledger. SBI offers monthly email statements. HDFC offers downloadable CSV/XLS card statements and PDF email statements; HDFC PDF layouts still need an adapter, so use the supported spreadsheet export for now. IDFC provides account-statement download through its app.

Official guides:
- SBI: https://www.sbicard.com/en/faq/statement-billing-related.page
- HDFC: https://www.hdfc.bank.in/need-help/mobile-banking-faqs
- IDFC: https://www.idfcfirst.bank.in/customer-care-sr/categories/accounts/statement-of-account-request

## Further work

### Branches and releases

`develop` contains the current work-in-progress application. `main` is reserved for the first validated stable release; there is no stable release yet. Test changes on `develop`, back up the live database before upgrades, then promote an approved version to `main` and tag it. Git rollback changes code only: it does not reverse database migrations. Use a separate checkout with a separate database for experiments; switching branches in the same directory shares `finance.db`.

Only application source, synthetic tests and documentation belong in Git. SQLite databases (including journal/WAL files), backups, statement PDFs/spreadsheets/CSVs, secrets, exports and personal one-off maintenance scripts are ignored. `.gitignore` is a safety net, not encryption: inspect staged files before every push and never force-add private files. Windows Credential Manager secrets are not part of the repository.

Statement balance reconciliation, account-number-based identity, transaction-email parsing/reconciliation, background Gmail polling, original-file retention, advanced refund-to-purchase linking, audit-history UI and full backup restore UI remain separate follow-up work. Category rules can be managed in Categories & badges. Recategorising already imported ambiguous credits requires user review. Existing zero-valued transactions cannot be reconstructed without the source statement.

## Saved statement passwords (Windows)

Install requirements.txt and run Ledger under your normal Windows user. In Import & accounts, use Statement passwords to save, replace or remove a password. Passwords use the explicit Windows keyring backend (no plaintext fallback). SQLite stores a random credential reference only; account renames preserve it. Deleting an empty account removes its credential, while archiving retains it.

For a locked PDF choose its PDF password account, preview, then confirm. Preview locked files for one password account at a time. Password selection and destination detection are independent; inspect the destination in the preview. Passwords are passed to the PDF parser in memory; no decrypted PDF is deliberately written. Upload handling can spool the original encrypted upload to an OS temporary file. Python memory and Windows paging are not guaranteed securely erased. Unlocking does not add support for new PDF layouts: currently SBI and CRED/IndusInd PDFs are supported.

Secrets are not returned by an API or stored in browser storage, logs, exports or database backups. The vault is scoped to your Windows user; backups restored on another machine need passwords reentered. It does not protect against malware or other programs running as your user. Run only on 127.0.0.1, not your LAN. Host/origin checks, frame denial and a per-process token on credential endpoints protect against browser cross-site access; this is not a multi-user login system. Refresh the page after restarting Ledger.

## Read-only Gmail intake

### Statement identification rules

Under **Import & accounts → Gmail statement inbox → Statement identification rules**, map an exact sender plus a stable subject or PDF-filename keyword to a destination account and optional saved PDF-password account. Every filled condition must match, ignoring case. Use **Create statement rule** on a pending PDF to copy its actual sender; select the destination and the account whose password is already saved. For SBI, select your SBI card account for both fields if its password is saved there. Do not enter the password itself into a rule. Avoid month names and dates in keywords when they change between statements.

Rules suggest account/password choices for existing pending PDFs and future collected emails. They do not bypass approved-sender/security filters, fetch attachments, prove sender authenticity, support new PDF layouts or post transactions automatically. Ambiguous matches require manual selection. Preview still runs the PDF parser and account detection; if that destination differs from the suggestion, a warning appears. Review the destination and totals before confirming. Changing/removing a rule invalidates pending previews and leaves imported transactions untouched. Rules store account references only; passwords remain in Windows Credential Manager. Archived destinations/password accounts are not suggested. Deleting an empty destination account removes its rules; deleting a password account clears that rule's password selection.

### Gmail setup and sync

**Sync & add alerts** now automatically posts supported transaction emails when issuer, account type and last four digits match a previously confirmed account mapping (or an existing confirmed card identity). A name-only account guess is not enough. For an unknown account ending, preview and confirm one alert to establish ownership; later syncs can add its alerts automatically. This does not cryptographically authenticate email senders. Sender restrictions and conservative parsers remain in force. IDFC merchant-less alerts retain the placeholder until statement reconciliation; balances are never treated as spending.

Sync checks duplicates immediately before inserting: suspected same-account/signed-amount overlaps within three days enter transaction Review and do not count in totals. Unmapped or unsupported alerts remain in the Gmail inbox. Already-processed messages are skipped. Each scan handles up to 50 new page results plus up to 50 previously collected unresolved alerts, and displays added/review/ignored/unsupported/skipped/PDF counts. PDF statements still require preview and confirmation. Undoing an email import suppresses automatic re-add for that item; explicitly preview and confirm to reimport it.

On statement import, a unique email candidate with a matching description or shared numeric transaction reference can reconcile in place (same account/amount, within three days, and a unique matching statement row). Amount alone, including an IDFC placeholder, is not enough for automatic reconciliation. Such entries go to Review, where **Use statement details for email #…** lets you confirm the pairing. The original email transaction ID is retained; untouched fields gain statement details and manual changes are preserved. The redundant statement review row moves to Trash. The app stores before/after snapshots and original statement fields/fingerprint so reimports can still be detected even after a merchant edit.

Import history reports reconciled counts. Undoing that statement restores the email entry if it has not been edited since; otherwise Undo stops to protect those edits. Undo the statement reconciliation before undoing or moving the original email batch. These safeguards are not a guarantee of complete reconciliation: different amounts, dates outside the window, or unsupported templates still need manual review.

In Import & accounts, open **Gmail statement inbox → One-time Gmail setup**.

1. In your own Google Cloud project, enable Gmail API. Configure the OAuth consent screen as External for a personal Gmail account; add the dedicated forwarding mailbox as a test user. Create an OAuth client of type **Desktop app**, not Web application or service account, and download its JSON. [Google setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python).
2. Enter the dedicated mailbox. New setups default to **Read emails from all senders** and **Scan all available history**; no sender list or start date is needed. Alternatively, turn these options off to restrict senders or set a start date. Existing configurations retain their previous restrictions until you save changes. Upload the downloaded client JSON into Ledger's local form. It is stored in Windows Credential Manager, not SQLite. Saving configuration restarts pagination and rechecks ignored messages.
3. Click **Connect with Google**, then **Continue to Google sign-in**. Sign in yourself and consent to read-only Gmail access. Ledger verifies the connected address matches your configuration. OAuth uses a temporary loopback callback with state and PKCE; callbacks time out after five minutes and authorization URLs/codes are not logged. No Google password is stored by Ledger.
4. Click **Sync & add alerts**. Each click scans up to 50 page results plus up to 50 unresolved backlog alerts; **Continue sync** handles subsequent pages. Spam and Trash are not scanned. The start date uses this laptop's local midnight. Repeated scans use message/part IDs to avoid re-staging messages; partial failures can be retried. Sync runs only when requested; the laptop/app must be running.
5. PDFs from approved senders appear as pending items. Choose a fallback account and, for locked PDFs, a saved password account. Preview, check detected destination and totals, then confirm. Changing choices requires another preview. Original attachment bytes are fetched on demand and not archived on disk or in SQLite. File signatures and a 25 MB limit are checked.

Only `gmail.readonly` is requested. It grants read access to the whole connected mailbox, not just approved senders or labels. Sender filtering is not cryptographic proof of authenticity, so no automatic posting is enabled. In restricted-sender mode, unknown senders are inspected as metadata only; in all-senders mode, every scanned message's content may be fetched for classification. Plain text and inert HTML text are checked; recognized verification/security emails and unrelated messages are ignored. Classification is conservative and rule-based, not a guarantee of perfect detection. Bodies/HTML and attachment bytes are not saved in SQLite. Local intake records retain mailbox, sender, subject, received date, Gmail IDs, filenames, classification and import links; they are included in database backups. No remote images, scripts or statement links are opened automatically. HDFC bank website downloads remain manual. All-history scanning removes the date cutoff and includes archived mail, but excludes Spam/Trash and cannot access old messages that were never forwarded to this mailbox. Continue through each page to complete the initial history scan.

Unsupported or unmapped transaction alerts appear as **Needs review**; supported alerts with confirmed account endings can auto-add on Sync. IDFC FIRST Bank debit/credit alerts and IndusInd approved-purchase alerts now support **Preview transaction email → Confirm and add transaction**. Check the account, edit the description/category/type if needed, then confirm. IDFC alerts may omit the merchant; the parser does not invent one or mistake the balance for the amount. Category keyword rules supply an initial category when the parsed description contains a matching keyword. Email-added entries are explicitly labelled provisional and count in totals when active; this is not statement verification. Preview expires after 30 minutes and changing account requires a new preview. Repeated confirmation is idempotent.

Same-account, same-signed-amount entries within three days are possible overlaps, not proven duplicates. Email confirmations with overlaps go to Review without entering totals. Later statement imports reconcile strong unique matches; uncertain overlaps still require the Review action described above. Different settled amounts or dates outside that window can still escape detection. Compare the statement and email entry, discard the redundant entry, and retain one correct record. Undo is available by import batch and returns alerts to Needs review (PDFs to pending). Unsupported templates stay unposted. Exact PDFs imported from two emails remain blocked using content hashes.

Turn on **Developer mode** in the sidebar, then open **Parser workspace**. It lists built-in email and manual import formats, and supports custom email, PDF-text and spreadsheet/CSV extraction definitions. Choose a template or open a JSON definition, edit its fields, test a redacted sample, inspect the results, then save and optionally enable it. Definitions must pass a test before saving. Disable or remove a custom parser without changing previously imported transactions. Built-ins remain available and cannot be removed here.

Email definitions require an exact sender, a literal marker, issuer/account type, and named extraction groups for date, amount and account ending. PDF patterns require a literal marker and date/description/amount groups. Spreadsheets map exact column headers. Patterns have execution time limits; no uploaded Python or JavaScript is executed. Custom parsers take precedence when they match; multiple custom matches stop rather than guessing. A successful test verifies extraction, **not completeness or sender authenticity**. Compare row counts and totals with the source before trusting a format. Image-only PDFs require a separate OCR workflow and are not supported by these text patterns.

Custom definitions live in the local SQLite database (and database backups); test samples are not persisted. The toggle is a UI preference, not an access-control boundary. Existing localhost/token protections apply to developer endpoints. Trusted email modules still live in `parsers/`; see [the extension contract](parsers/README.md) for code-level contributions. Existing manual parsers remain built-in application functions, exposed alongside custom definitions through the import dispatcher.

The HDFC credit-card parser supports the observed `alerts@hdfcbank.bank.in` debit alert format, including amount, merchant, card ending and timestamp. Refund/repayment templates are not inferred from that debit template. Previously unsupported items can be previewed again; confirm the correct account once if its ending is not mapped yet. No emails are imported merely by installing the parser.

Import & accounts now separates Email inbox, Upload statements, Import history, and Accounts & security. Categories, keyword rules and badges have their own tabs. Existing controls and workflows are retained.

Only the refresh token is stored in the vault; access tokens are obtained in memory. Disconnect removes the local refresh token but retains configuration and imported/review records. Revoke access in [Google Account permissions](https://myaccount.google.com/permissions) if you also want to remove Google's grant. External OAuth projects in Testing commonly have seven-day refresh tokens; reconnect when prompted. [Google token expiration documentation](https://developers.google.com/identity/protocols/oauth2#expiration).

Tests: `python -m unittest test_app test_credentials.CredentialTests test_gmail.GmailTests -v`. Gmail tests use synthetic email payloads, mocked network calls and a temporary database, not your mailbox or real credentials. Live sign-in/download verification requires your Google setup and consent.
