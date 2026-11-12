"""Secrets (sign-in tokens, client IDs) live in the operating system's
keychain, never in files. On Windows that is Credential Manager: open
"Credential Manager" from the Start menu and look under Windows Credentials
for entries named JARVIS to see or remove them.
"""

from __future__ import annotations

SERVICE = "JARVIS"


class SecretsUnavailable(Exception):
    pass


def _keyring():
    try:
        import keyring
    except ImportError:
        raise SecretsUnavailable('The keychain library is missing. Run:  pip install -e "."') from None
    return keyring


def get(name: str) -> str | None:
    return _keyring().get_password(SERVICE, name)


def put(name: str, value: str) -> None:
    _keyring().set_password(SERVICE, name, value)


def delete(name: str) -> None:
    keyring = _keyring()
    try:
        keyring.delete_password(SERVICE, name)
    except Exception:
        pass  # it was not there
