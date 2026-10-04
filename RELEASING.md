# Personal-use v1 release checklist

Ledger is a single-user Windows application bound to `127.0.0.1`, not a public hosted service.

## Verify the candidate

From the project folder, with Python development dependencies and Node.js installed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -q
Get-ChildItem -Name test_*.js | ForEach-Object { node $_; if ($LASTEXITCODE -ne 0) { throw "Failed: $_" } }
```

The tests use synthetic data and temporary databases. An optional encrypted-PDF test requires `LEDGER_PDF_TEST_PYTHON` to point to a Python interpreter with reportlab installed; otherwise it is skipped. Gmail and credential tests mock external services, so also confirm the normal Gmail flow in your own installation before release.

- Follow README setup in a fresh environment before declaring a stable release.
- Check both dashboard modes, chart/category navigation, transaction edits and bulk actions.
- Confirm statement preview, duplicate review, reconciliation and import undo.
- Download a database backup and keep it privately. The release smoke test checks restoration into a separate temporary database; never restore a test over your real data.

## Publish only application files

1. Review `git status` and `git diff`. Include the new source modules, tests and manual.
2. Verify staged paths with `git diff --cached --name-only`. Do not include databases, statements, backups, OAuth JSON, tokens, passwords or local maintenance scripts.
3. Commit the verified candidate on `develop`.
4. Once the checks above are complete, merge the candidate into stable `main` and tag `v1.0.0`. Continue new work on `develop`.

No branch merge, tag or push is performed by the cleanup itself. Keep the README clone branch as `develop` until `main` contains the release, then update it to `main`.

## Scope and limitations

- Imported data can be incomplete; uncertain duplicates and unsupported formats still require review.
- Salary boundaries may be estimated when a salary is missing. Balance estimates are not bank-verified balances.
- Windows Credential Manager secrets are not included in SQLite backups. Reconnect Gmail and re-enter statement passwords when moving to another Windows account/computer.
- This checklist is not a security audit or a guarantee of compatibility with every future bank statement format.
