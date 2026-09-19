"""Signing in to Google as the Puppet Master.

Puppet Strings used to read the sheets as a service account, which meant every new sheet
had to be shared with a robot before it could be opened, and meant the Drive browser could
show nothing: a service account has no My Drive, nothing shared with it and no shared
drives. So it signs in as the person instead. The first run opens a browser for consent,
the token is kept in the config folder, and every run after that is silent until the
account is changed from the Configure pane.

The OAuth client itself is not Puppet Strings' to ship, so `[auth] client_secrets` in
config.toml points at the client JSON downloaded from the Google Cloud console. A service
account in `[auth] credentials` still works and is used when nobody has signed in, so an
existing install keeps running until it is switched over.
"""

import json
import os
from pathlib import Path

# Reading and writing the sheets, browsing Drive, making the schedule folders and the day
# spreadsheets inside them, and the address of whoever signed in so the Configure pane can
# say which account is in use. `drive.file` covers only what Puppet Strings makes or is
# given, which is why browsing needs `drive.metadata.readonly` beside it.
SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
)
USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"


class AuthError(Exception):
    """Signing in is not possible or did not happen. The message says what to do about it."""


def stored(token: Path) -> object | None:
    """The signed-in credentials, refreshed if they had expired, or None if nobody is.

    A token that cannot be refreshed — revoked, or its scopes changed — is treated as
    nobody being signed in, so the app asks again rather than failing on every read.
    """
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = token.expanduser()
    if not token.exists():
        return None
    try:
        credentials = Credentials.from_authorized_user_file(str(token), list(SCOPES))
    except (ValueError, json.JSONDecodeError):
        return None
    if credentials.valid:
        return credentials
    if not credentials.refresh_token:
        return None
    try:
        credentials.refresh(Request())
    except GoogleAuthError:
        return None
    _write(token, credentials)
    return credentials


def sign_in(config) -> object:
    """Open a browser for consent and remember the result. Raises AuthError.

    A downloaded release has camp's OAuth client built into it, so there is nothing to set
    up. A source checkout has none, and falls back to the client JSON named in config.toml.
    """
    from google.auth.exceptions import GoogleAuthError
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        if config.client_id and config.client_secret:
            flow = InstalledAppFlow.from_client_config(_client_config(config), list(SCOPES))
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_client_file(config)), list(SCOPES)
            )
        credentials = flow.run_local_server(port=0, prompt="consent")
    except (GoogleAuthError, ValueError, OSError) as e:
        raise AuthError(f"Could not sign in: {e}") from e
    _write(config.token.expanduser(), credentials)
    return credentials


def _client_file(config) -> Path:
    """The OAuth client JSON, or an AuthError saying how to get one."""
    client_secrets = config.client_secrets.expanduser()
    if not client_secrets.exists():
        raise AuthError(
            f"No Google OAuth client at {client_secrets}. A downloaded release has camp's "
            "built in; running from source, make a Desktop app OAuth client in the Google "
            "Cloud console, download its JSON, and choose it in the Configure pane."
        )
    return client_secrets


def _client_config(config) -> dict:
    """The built-in client, shaped the way an installed-app flow wants it."""
    return {
        "installed": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def sign_out(token: Path) -> None:
    """Forget the signed-in account. The next sign-in asks which account to use."""
    token.expanduser().unlink(missing_ok=True)


def account(credentials: object) -> str:
    """The address of the account signed in, or "" if Google will not say."""
    from google.auth.transport.requests import AuthorizedSession

    try:
        response = AuthorizedSession(credentials).get(USERINFO, timeout=20)
        response.raise_for_status()
        return response.json().get("email", "")
    except Exception:  # noqa: BLE001 - only ever decoration for the Configure pane
        return ""


def service_account(credentials: Path) -> object | None:
    """The old service account, for an install that has not signed in yet."""
    from google.oauth2 import service_account as sa

    credentials = credentials.expanduser()
    if not credentials.exists():
        return None
    return sa.Credentials.from_service_account_file(str(credentials), scopes=list(SCOPES))


def _write(token: Path, credentials: object) -> None:
    """Keep the token where only its owner can read it.

    The file is opened with its permissions rather than given them afterwards: it holds a
    refresh token that stays good until somebody revokes it, and a `chmod` after the write
    leaves it readable by anyone the umask allows for as long as the write takes. Opening
    it this way means it is never, for an instant, a file another account could read.
    """
    token.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(handle, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())
    token.chmod(0o600)  # O_CREAT leaves an existing file's own permissions alone
