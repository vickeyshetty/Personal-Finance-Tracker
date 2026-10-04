# Ledger — Personal Finance Tracker

A personal finance app that runs locally on your computer.

## Install on Windows

1. Install **Python 3.11 or newer** and **Git**.
2. Open PowerShell and download the app:

   ```powershell
   git clone --branch develop https://github.com/vickeyshetty/Personal-Finance-Tracker.git
   cd Personal-Finance-Tracker
   ```

3. Create a virtual environment and install dependencies:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Start the app from the project folder:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
   ```

5. Open [Ledger](http://127.0.0.1:8000/) in your browser.

To use it again, open PowerShell in the project folder and repeat step 4. Press **Ctrl+C** to stop the app.

Your database is created automatically on first startup. Keep the app local; it is intended for one user. Gmail integration is optional.

The `develop` branch is the current work-in-progress version.

## Using Ledger

See the [User manual](USER_MANUAL.md) for imports, Gmail setup, dashboards, categories, badges, and backups.
