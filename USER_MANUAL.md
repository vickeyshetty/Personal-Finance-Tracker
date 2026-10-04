# Ledger user manual

For installation and the start command, see the [README](README.md).

## Contents

- [First use and accounts](#first-use-and-accounts)
- [Importing statements](#importing-statements)
- [Review, duplicates, and undo](#review-duplicates-and-undo)
- [Dashboard and salary cycles](#dashboard-and-salary-cycles)
- [Transactions and accounting](#transactions-and-accounting)
- [Categories and keyword rules](#categories-and-keyword-rules)
- [Badges](#badges)
- [Gmail integration](#gmail-integration)
- [Bank balance snapshots](#bank-balance-snapshots)
- [Backups and privacy](#backups-and-privacy)
- [Developer mode](#developer-mode)
- [Development and troubleshooting](#development-and-troubleshooting)

## First use and accounts

Ledger starts with an empty database, default categories, and a placeholder **Primary bank** account. No personal transactions or credentials are included.

Open **Import & accounts → Accounts & security** to add, rename, archive, or delete accounts. Use bank accounts for savings/current accounts and credit-card accounts for cards. Inspect the destination account whenever previewing an import; a recognized statement layout alone is not proof of account ownership.

## Importing statements

1. Open **Import & accounts → Upload statements**.
2. Choose your statement files. Multiple CSV, XLS, XLSX, and supported PDF files can be selected together.
3. Select a fallback account. For an encrypted PDF, also select its saved password account.
4. Click **Preview statements**.
5. Check the detected destination, transaction rows, debit/credit totals, and duplicate counts.
6. Correct the destination if needed, then confirm each import.

Built-in formats include the supported HDFC/IDFC bank spreadsheets, HDFC card spreadsheets, and SBI, CRED/IndusInd, HDFC Millennia, and IDFC savings text-based PDFs. Not every layout from these banks is supported. Scanned/image-only PDFs require a separate OCR workflow.

IDFC consolidated savings PDFs must contain one savings account. The parser checks debit/credit counts, totals, every running balance, and the closing balance before returning transactions. A missing or unreadable row stops the import. Statement rules can select the destination account and its saved password for monthly emails; preview and confirmation are still required.

For HDFC Millennia PDFs, dated transaction rows that cannot be parsed stop the import rather than silently disappearing. Rewards, loan summaries, and promotional EMI totals are not transactions.

### Password-protected PDFs

Save PDF passwords under **Accounts & security → Statement passwords**. Passwords are stored in Windows Credential Manager for your Windows user, not as plaintext in SQLite. The database stores a credential reference; renaming an account preserves it.

The password account unlocks the document; the destination account receives its transactions. These are independent choices. Preview locked files for one password account at a time. Unlocking a file does not add support for an unknown layout.

### Import history

Search **Import history** by filename, account, date, or import ID. Each batch shows its row count and available review, move, and undo actions.

- **Review duplicates** opens just that batch's pending candidates.
- **Move to selected account** corrects an import made into the wrong account.
- **Undo import** moves the batch's entries to Trash, subject to reconciliation safeguards below.

Older uploads without batch IDs appear as historical groups, grouped by filename and account. Moving or undoing one of these groups can affect several old uploads.

Keep a download folder for monthly statements and import several files together. HDFC bank statements accessed through a password-protected bank webpage remain a manual download.

**Check completeness yourself:** preview counts and skipped-row counts do not certify that every transaction was extracted. Ledger does not automatically reconcile all printed opening/closing statement balances.

## Review, duplicates, and undo

Possible duplicates go to **Review** and do not count in spending until accepted. Filter Review by import to distinguish new candidates from older ones.

- **Merge with existing email** uses statement details to enrich the matching email entry and counts the transaction once. Manual edits are preserved. The redundant statement row moves to Trash.
- **Keep both** retains two transactions. Use only when they really are separate payments.
- **Discard** keeps the existing entry and sends the candidate to Trash.

Automatic email/statement reconciliation requires a unique match on account, signed amount, and the same calendar date, plus matching description or a shared numeric reference. Amount alone is not enough. Ambiguous matches need review; different dates or settled amounts can escape detection.

Undoing a reconciled statement restores the original email entry only if it has not changed afterward. Otherwise undo stops to protect the later edits. Undo the statement reconciliation before undoing or moving its original email batch.

Trash entries can be restored. Restoring preserves the previous exclusion/review state; it does not automatically turn an excluded transfer into spending. Reimporting a fully undone statement is possible, while remaining active/review records still participate in duplicate checks.

## Dashboard and salary cycles

**Calendar month** and **Salary cycle** use the same dashboard: salary received, net spending, investments, category donut, food orders, refunds, trend, merchants, bank cash flow, and detailed entry lists.

- Select a month/cycle or click a trend bar to change the reporting period.
- Click a donut slice or category to open Transactions filtered to its exact date range.
- The donut and category ranking show purchases/fees before refunds. Net spending subtracts confirmed refunds.
- Investments are separate from everyday spending in both modes.
- Bank cash flow shows bank movements: card repayments are bank outflows; card purchases are counted in spending, not again in bank cash flow.
- Current bank balance snapshots and historical recurring-charge suggestions are labeled separately because they do not follow the selected period.

### Set up salary cycles

1. Open **Set up / manage salary cycles** on Overview.
2. Select an active bank credit categorized as **Salary**.
3. Confirm the cycle's start date and save.
4. Confirm the next salary when it arrives to close the previous cycle.

After the first confirmed start, each following month gets a cycle automatically. The first eligible Salary credit that month starts it; further salary credits are included without extra boundaries. For example, an August 31 payday funds the cycle through September 29 when the next payday is September 30. If salary is missing, a clearly marked estimated boundary uses your confirmed payday (month-end stays month-end), so missing months do not merge into one long period. Adjust an automatic start with **Edit** to save a manual override. You can edit or remove manual boundaries without changing transactions. All transactions on a boundary date belong to the new cycle, regardless of time of day.

The chart keeps recent periods visible when you select a bar. Selecting one updates the whole dashboard and returns you to its summary; the calendar/salary mode stays unchanged.

If salary is not imported, create a date-only cycle. Missing salary displays **Not available**, not zero. A salary linked to a cycle remains allocated to it if you adjust its start date; it cannot fund two salary cycles. Other eligible Salary credits inside the interval are included without creating a new cycle.

Deleting, excluding, or recategorizing a linked salary can invalidate its boundary. Edit the setup to resolve it.

The dashboard does not show a salary-remaining estimate. Other credits are not assumed to be salary. Missing statements make reports incomplete.

## Transactions and accounting

Search Transactions by description, account, category, amount, or date. Combine account, month/date-range, category, badge, and status filters. **Clear search & filters** resets them. Dates display month names; debits are red and credits green.

Select individual rows or use the header checkbox to select all matching current transactions. Review and Trash entries are not included in bulk selection. Use **Categorise selected** or **Badges for selected…** for bulk changes.

Use **Edit** to change a transaction's details, category, type, exclusion, or badges. Categories describe purpose; type determines accounting:

| Type | Meaning |
| --- | --- |
| Purchase / fee | Active charges count as spending. |
| Refund / cashback | Reduces spending in the period the credit arrives. |
| Card repayment | Excluded from spending; card credits appear separately as repayments received. |
| Self-transfer | Excluded from spending for any amount. |
| Income / salary | Money received as income, subject to its category. |
| Unclassified credit | Not automatically assumed to be a refund or salary. |

Use **Edit → Pair / mark self-transfer** to pair opposite entries or mark one side manually. Suggestions cover seven days. Editing key details of a linked transfer can unlink the pair; the other side remains excluded until changed separately.

Email-origin entries have an expandable **Email alert** note. They are provisional until verified against a statement, even when they count in current totals.

## Categories and keyword rules

Open **Categories & badges** to manage categories. Removing a category moves affected entries—including Review and Trash—to Uncategorized and removes rules targeting it. Amounts and transaction types remain unchanged. Core accounting categories cannot be removed. Removed defaults stay removed after restart.

Useful categories include:

- **Subscriptions:** recurring services you want grouped in the donut and monthly totals. Bulk-categorize old charges and add rules for future imports.
- **Online food order:** Swiggy food orders.
- **Quick commerce:** Instamart and Zepto.
- **People:** money sent to/received from people; type still determines accounting.
- **Investments:** shown separately on the shared dashboard.

### Keyword rules

1. Open the **Keyword rules** tab.
2. Enter one keyword or phrase and select its category.
3. Click **Add rule**. When editing, the button becomes **Save changes**.
4. **Cancel / clear** leaves editing and resets the form.

Matching is literal and case-insensitive; the longest matching phrase wins. Saving an existing keyword updates its category. Rules apply to future imports, not retrospectively; bulk-categorize existing entries. Recognized card repayments retain their accounting category. Category rules do not change transaction types.

## Badges

Badges describe extra characteristics, such as UPI, EMI, or a named trip. They can overlap and do not change totals. They are informational labels, not verified payment metadata.

Under **Categories & badges → Badges**, enter a name and optional comma-separated keywords. Keywords match any listed phrase; whole-word matching is optional. Leave keywords empty for a manual-only badge. Saving the same name updates its definition.

For one transaction, open **Edit → Transaction badges** and click badge buttons to select/deselect them. Highlighted buttons are selected. Save changes to apply. Untouched badges keep their automatic/manual behavior; a manually removed badge stays hidden even if its keyword matches.

For multiple transactions, select rows and choose **Badges for selected…**:

- **Add:** assigns selected badges without removing other badges.
- **Remove:** hides selected badges, including automatic keyword matches.
- **Automatic:** clears the selected manual overrides and returns to keyword matching.

Bulk changes are atomic. Manual choices persist across reloads and statement enrichment. Removing a badge definition clears its manual overrides. Use the Transactions badge filter to find matching entries. Subscription spending uses the **Subscriptions category**, not a separate badge-spending dashboard.

## Gmail integration

Gmail is optional. A dedicated mailbox receiving forwarded bank emails limits the personal mail accessible to Ledger. Forwarding rules usually affect new mail; historical messages must actually exist in that mailbox to be scanned.

### Connect Gmail

1. Create your own Google Cloud project and enable Gmail API.
2. For personal Gmail, configure the OAuth audience as **External** and add the dedicated mailbox as a test user.
3. Create a **Desktop app** OAuth client and download its JSON.
4. In **Import & accounts → Email inbox → One-time Gmail setup**, enter the mailbox and upload that JSON.
5. Choose all senders/all available history, or restrict senders and set a start date.
6. Click **Connect with Google**, continue to sign-in, and authorize the dedicated mailbox yourself.
7. Click **Sync & add alerts**. Use **Continue sync** if more pages remain.

Ledger requests read-only access to the whole connected mailbox, not just selected senders. It does not send, delete, or mark emails read. Sync is manual; the app and laptop must be running. Spam and Trash are excluded. Each scan handles up to 50 new page results and up to 50 unresolved collected alerts. Processed messages are skipped; partial failures can be retried.

OAuth client configuration and refresh tokens use Windows Credential Manager. Access tokens are held in memory. The connection must match the configured mailbox. A temporary local callback uses state and PKCE; no Google password is stored. If Google expires a testing authorization, reconnect. Disconnect removes the local refresh token but retains imported data; revoke Google's grant separately if needed.

### Alerts versus PDF statements

Supported IDFC bank, HDFC bank/card, and IndusInd card alerts can post automatically when the account ending has been confirmed. Unknown mappings and unsupported templates stay in the inbox. Preview and confirm a supported alert once to establish its account mapping. Balance notices are not spending.

Suspected duplicates go to transaction Review immediately before insertion. An email lacking a merchant retains an explicit placeholder until a statement supplies more detail. An unclassified credit is not automatically a refund or salary.

PDFs require preview and confirmation. Select destination/password accounts, inspect extraction and totals, then confirm. Changing choices requires a new preview. Repeated confirmations are protected against reimport; identical PDF attachments are also checked by content hash. Undoing an email import suppresses its automatic re-add; explicit preview/confirmation is needed to import it again.

### Statement identification rules

In **Email inbox → Statement identification rules**, map an exact sender plus stable subject/PDF filename keywords to destination and optional password accounts. All filled conditions must match. Avoid changing month/date fragments in keywords.

Use **Create statement rule**, **Edit statement rule**, or **Resolve matching rules** on inbox items, including imported PDFs. Rule changes do not reimport transactions and invalidate pending previews. Rules suggest account/password choices; they do not prove sender authenticity, add parser support, or bypass preview confirmation. Passwords themselves stay in the credential vault.

### Gmail safety and limitations

Sender filtering is not cryptographic authentication. Supported alerts with confirmed account endings can still auto-post, so review sources and totals. Plain text and inert HTML text are parsed; no remote images, scripts, or bank links are opened automatically. HDFC bank website statement downloads remain manual.

Bodies and attachment bytes are not retained in SQLite. Intake metadata—sender, subject, dates, message IDs, filenames, classifications, and import links—is retained and included in database backups. Attachments are fetched on demand, checked for file signatures and a 25 MB limit, and not archived as original files.

## Bank balance snapshots

Overview separates the latest bank-reported available balance from the estimated balance. Currently the observed HDFC balance-email format is supported. Confirm an unlinked account ending before using it; that confirmation also enables supported transaction alerts for that ending.

The estimate adds active/excluded bank entries strictly after the snapshot date through today. Transfers and repayments affect balances even though they are excluded from spending. Same-day entries are not added when the email has no cutoff time; uncertainty is shown. Review, Trash, and future entries are omitted.

Conflicting or future snapshots suppress estimates; old updates are marked stale. Holds, uncleared funds, and missing entries can cause differences. This is not a certified live balance.

## Backups and privacy

`finance.db` contains private financial data. Startup creates one daily backup in `backups/`. **Download database backup** creates a consistent SQLite snapshot. **Export CSV** exports active/excluded ledger entries, not original statements or every stored setting. Keep another backup outside this laptop.

To restore: stop Ledger, preserve the current database under a different name, copy the chosen backup to `finance.db`, then restart. There is no browser restore control. Database rollback and Git rollback are different; reverting code does not undo database migrations.

Passwords are not included in database backups and must be reentered under a different Windows user or machine. Credential Manager does not protect against malware running as your user. SQLite/backups are private files, not an encrypted vault. Passwords are passed to parsers in memory; encrypted uploads may be spooled to temporary files, and memory/paging are not guaranteed securely erased.

Run only on **127.0.0.1**, not your LAN. Ledger has no multi-user authentication. Local host/origin checks, frame denial, and credential-operation tokens provide browser protections, not remote-access security. Refresh after restarting the server.

Private databases, backups, statements, exports, and secrets are excluded from Git. Check staged files before pushing; `.gitignore` is not encryption. Transaction audit snapshots exist, but an audit-history browsing UI is not yet provided.

## Developer mode

Enable **Developer mode** in the sidebar to open **Parser workspace**. It lists built-in parsers and supports custom email, PDF-text, and spreadsheet/CSV definitions.

1. Choose a template or open a definition JSON.
2. Edit its extraction fields and provide a redacted sample.
3. Test and inspect the output against the original rows/totals.
4. Save and optionally enable the definition.

Email definitions require an exact sender, literal marker, issuer/account type, and date/amount/account-ending extraction. PDF definitions need a marker and transaction fields; spreadsheets map column headers. No uploaded Python/JavaScript is executed, and regex execution is limited. Matching custom parsers take precedence; ambiguous matches stop rather than guess.

A successful test proves extraction, not completeness or authenticity. Built-ins cannot be removed from this screen. Disabling/removing custom parsers leaves imported data unchanged. Definitions are stored in SQLite/backups; samples are not persisted. Developer mode is a UI preference, not an access-control boundary. For trusted code-level extensions, see [parsers/README.md](parsers/README.md).

## Development and troubleshooting

`develop` contains work in progress; `main` is reserved for the first validated stable release. Back up the live database before upgrades. Use a separate checkout and database for experiments—switching branches in one folder shares the same database.

Run commands from the project folder. An error saying **Could not import module app** usually means the terminal is in the wrong directory or environment. Use the virtual environment command in the README. Stop an existing server with Ctrl+C before starting another on port 8000.

For automatic code reload:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

For automated checks (Node.js is optional for JavaScript checks):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
node --check static/app.js
node test_badges.js
node test_badge_toggles.js
node test_history_search.js
```

Tests use temporary databases and synthetic/mocked inputs. Live Gmail sign-in and downloads still require your own setup and consent.
### Ordering transactions within a day

Transactions remain newest-date first. Within each date, known times appear newest first, followed by entries with no known time in stable import-ID order. New email alerts retain an actual transaction time when their parser supplies one; otherwise linked email receipt times provide an approximation. Older email-linked entries also use their stored receipt time. Times display in IST; `≈` means email received time, not confirmed transaction time. Delayed or forwarded emails can therefore give an imperfect order.

When a supported statement supplies a transaction time, it takes priority over the actual alert time and approximate email receipt time. IDFC savings PDFs, HDFC card PDFs, and supported CSV/Excel date-time or separate Time columns preserve available times. Date-only statements do not invent midnight or erase existing timing. Statement time is labelled “statement” in the transaction list. Reconciling an email entry adopts the statement time; undoing that import restores the previous timing. Statement-only entries never inherit the statement email's arrival time. This changes display order only, not transaction dates, totals, or duplicate checks.
