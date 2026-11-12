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


def _guarded(action):
    """Run a keychain operation, turning its failures into one clear error."""
    keyring = _keyring()
    try:
        return action(keyring)
    except keyring.errors.KeyringError as exc:
        raise SecretsUnavailable(
            f"This computer's keychain could not be used ({type(exc).__name__}). "
            "On Windows, check that Credential Manager is available to your account."
        ) from None


def get(name: str) -> str | None:
    return _guarded(lambda k: k.get_password(SERVICE, name))


def put(name: str, value: str) -> None:
    _guarded(lambda k: k.set_password(SERVICE, name, value))


def delete(name: str) -> None:
    try:
        _guarded(lambda k: k.delete_password(SERVICE, name))
    except SecretsUnavailable:
        pass  # it was not there, or there is no keychain to delete from
