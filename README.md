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

- Purchase / fee: counts as spending when active.
- Refund / cashback: reduces spending in the month the credit arrives, even if the purchase was in another month.
- Card repayment: excluded from spending; card-side credits appear separately as repayments received.
- Self-transfer: excluded for any amount. Select exactly one opposite entry or mark one side manually. Suggestions cover seven days; absence of a suggestion doesn't prevent marking either side.
- Unclassified card credit: visible for review, not assumed to be a refund.

Categories describe purpose; transaction type controls accounting. Use Edit to correct both. Changing a linked transfer in Edit removes the link; the opposite side remains excluded until edited separately.

The main metric is this calendar month's spending after refunds. The six-month chart includes zero months and progresses oldest-to-newest from left to right. Click a month to inspect its purchases, refunds, category ranking and entries; the main current-month metric stays unchanged. Category ranking is by gross spending, with separate refund and net columns. Swiggy food orders use Online food order; Instamart and Zepto use Quick commerce. These rules apply to future imports too. People is available for manually categorising money sent to or received from people; transaction type still controls whether it affects spending. It shows imported data only, not live bank balances. Recurring suggestions require three similar amounts spaced 25–35 days apart.

## Data protection

`finance.db` contains private financial data. Startup creates one daily backup in `backups/`; Download database backup creates an additional consistent SQLite snapshot. Export CSV downloads the active/excluded ledger, not the original bank statements. These are backups/exports, not a bank synchronisation service.

To restore a full backup: stop the server, preserve the current finance.db under a different filename, copy the chosen backup to finance.db, then restart. No browser restore control is provided yet. Store another backup outside this computer. Database and backup files are excluded from Git.

Migrations run once; restarting does not recategorise or reassign existing transactions. Current and original duplicate fingerprints are retained separately. An audit table records transaction snapshots for edits, moves and deletion; audit browsing is not exposed in the UI yet.

## Checks

Use the virtual environment's Python (`.\.venv\Scripts\python.exe`) for these commands if it is not activated.

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest test_app test_credentials.CredentialTests test_gmail.GmailTests -v
node --check static/app.js
node --check static/gmail.js
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

Statement balance reconciliation, account-number-based identity, transaction-email parsing/reconciliation, background Gmail polling, original-file retention, advanced refund-to-purchase linking, audit-history UI and full backup restore UI remain separate follow-up work. Category rules can be added and deleted in Import & accounts. Recategorising already imported ambiguous credits requires user review. Existing zero-valued transactions cannot be reconstructed without the source statement.

## Saved statement passwords (Windows)

Install requirements.txt and run Ledger under your normal Windows user. In Import & accounts, use Statement passwords to save, replace or remove a password. Passwords use the explicit Windows keyring backend (no plaintext fallback). SQLite stores a random credential reference only; account renames preserve it. Deleting an empty account removes its credential, while archiving retains it.

For a locked PDF choose its PDF password account, preview, then confirm. Preview locked files for one password account at a time. Password selection and destination detection are independent; inspect the destination in the preview. Passwords are passed to the PDF parser in memory; no decrypted PDF is deliberately written. Upload handling can spool the original encrypted upload to an OS temporary file. Python memory and Windows paging are not guaranteed securely erased. Unlocking does not add support for new PDF layouts: currently SBI and CRED/IndusInd PDFs are supported.

Secrets are not returned by an API or stored in browser storage, logs, exports or database backups. The vault is scoped to your Windows user; backups restored on another machine need passwords reentered. It does not protect against malware or other programs running as your user. Run only on 127.0.0.1, not your LAN. Host/origin checks, frame denial and a per-process token on credential endpoints protect against browser cross-site access; this is not a multi-user login system. Refresh the page after restarting Ledger.

## Read-only Gmail intake

In Import & accounts, open **Gmail statement inbox → One-time Gmail setup**.

1. In your own Google Cloud project, enable Gmail API. Configure the OAuth consent screen as External for a personal Gmail account; add the dedicated forwarding mailbox as a test user. Create an OAuth client of type **Desktop app**, not Web application or service account, and download its JSON. [Google setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python).
2. Enter the dedicated mailbox. New setups default to **Read emails from all senders** and **Scan all available history**; no sender list or start date is needed. Alternatively, turn these options off to restrict senders or set a start date. Existing configurations retain their previous restrictions until you save changes. Upload the downloaded client JSON into Ledger's local form. It is stored in Windows Credential Manager, not SQLite. Saving configuration restarts pagination and rechecks ignored messages.
3. Click **Connect with Google**, then **Continue to Google sign-in**. Sign in yourself and consent to read-only Gmail access. Ledger verifies the connected address matches your configuration. OAuth uses a temporary loopback callback with state and PKCE; callbacks time out after five minutes and authorization URLs/codes are not logged. No Google password is stored by Ledger.
4. Click **Sync and review**. Each click scans up to 50 messages; **Continue sync** handles subsequent pages. Spam and Trash are not scanned. The start date uses this laptop's local midnight. Repeated scans use message/part IDs to avoid re-staging messages; partial failures can be retried. Sync runs only when requested; the laptop/app must be running.
5. PDFs from approved senders appear as pending items. Choose a fallback account and, for locked PDFs, a saved password account. Preview, check detected destination and totals, then confirm. Changing choices requires another preview. Original attachment bytes are fetched on demand and not archived on disk or in SQLite. File signatures and a 25 MB limit are checked.

Only `gmail.readonly` is requested. It grants read access to the whole connected mailbox, not just approved senders or labels. Sender filtering is not cryptographic proof of authenticity, so no automatic posting is enabled. In restricted-sender mode, unknown senders are inspected as metadata only; in all-senders mode, every scanned message's content may be fetched for classification. Plain text and inert HTML text are checked; recognized verification/security emails and unrelated messages are ignored. Classification is conservative and rule-based, not a guarantee of perfect detection. Bodies/HTML and attachment bytes are not saved in SQLite. Local intake records retain mailbox, sender, subject, received date, Gmail IDs, filenames, classification and import links; they are included in database backups. No remote images, scripts or statement links are opened automatically. HDFC bank website downloads remain manual. All-history scanning removes the date cutoff and includes archived mail, but excludes Spam/Trash and cannot access old messages that were never forwarded to this mailbox. Continue through each page to complete the initial history scan.

Transaction alerts and financial emails without PDFs appear as **Needs review** and do not create ledger transactions. Bank-specific alert templates and alert-to-statement reconciliation still need implementation. Unsupported PDF layouts remain unimported with an error; an unlocked PDF is not necessarily a supported statement. Existing transaction duplicate review still applies to earlier manual imports. Exact PDFs imported from two emails are blocked using content hashes. Import history's Undo returns email items to pending.

Only the refresh token is stored in the vault; access tokens are obtained in memory. Disconnect removes the local refresh token but retains configuration and imported/review records. Revoke access in [Google Account permissions](https://myaccount.google.com/permissions) if you also want to remove Google's grant. External OAuth projects in Testing commonly have seven-day refresh tokens; reconnect when prompted. [Google token expiration documentation](https://developers.google.com/identity/protocols/oauth2#expiration).

Tests: `python -m unittest test_app test_credentials.CredentialTests test_gmail.GmailTests -v`. Gmail tests use synthetic email payloads, mocked network calls and a temporary database, not your mailbox or real credentials. Live sign-in/download verification requires your Google setup and consent.
