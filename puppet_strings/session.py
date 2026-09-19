"""Opening the sheets: whose Google account to read them as, and where to read them from."""

from pathlib import Path

from puppet_strings import google_auth
from puppet_strings.config import Config
from puppet_strings.sheets.source import CsvSource, SheetsSource, Source


def credentials(config: Config, interactive: bool = False) -> object:
    """Whoever is signed in, falling back to the old service account. Raises AuthError.

    `interactive` lets this open a browser for consent when nobody is signed in, which is
    what the app does on its first run; the command line asks instead of surprising a
    script with a browser window.
    """
    signed_in = google_auth.stored(config.token)
    if signed_in is not None:
        return signed_in
    robot = google_auth.service_account(config.credentials)
    if robot is not None:
        return robot
    if not interactive:
        raise google_auth.AuthError(
            "Nobody is signed in to Google. Open the app and sign in from Configure."
        )
    return google_auth.sign_in(config)


def open_source(config: Config, fixtures: Path | None, interactive: bool = False) -> Source:
    """The sheets, or a folder of CSV files standing in for them."""
    if fixtures:
        return CsvSource(fixtures)
    return SheetsSource(config.sheets, credentials(config, interactive), config.folders)
