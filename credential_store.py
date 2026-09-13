"""Windows-only secret storage. Never use keyring's auto-selected fallback."""
import sys


class VaultUnavailable(Exception):
    pass


def backend():
    if sys.platform != 'win32':
        raise VaultUnavailable('Statement passwords require Windows Credential Manager.')
    try:
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    except Exception:
        raise VaultUnavailable('Windows Credential Manager is unavailable. Install requirements.txt and restart Ledger.') from None


def read(key, service='Ledger.StatementPasswords'):
    try:
        return backend().get_password(service, key)
    except VaultUnavailable:
        raise
    except Exception:
        raise VaultUnavailable('Could not access Windows Credential Manager.') from None


def save(key, password, service='Ledger.StatementPasswords'):
    try:
        backend().set_password(service, key, password)
    except Exception:
        raise VaultUnavailable('Could not save the password in Windows Credential Manager.') from None


def remove(key, service='Ledger.StatementPasswords'):
    try:
        vault = backend()
        if vault.get_password(service, key) is not None:
            vault.delete_password(service, key)
    except Exception:
        raise VaultUnavailable('Could not remove the password from Windows Credential Manager.') from None
