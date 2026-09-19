"""Listing Google Drive, so the Configure pane can browse it and the import can read a folder.

Everything here is the Drive v3 `files.list` endpoint with the flags that make shared
drives visible; there is no client library because one endpoint does not need one. Every
listing is of one place — a folder, the root of My Drive, what has been shared with the
person, or the shared drives themselves — and returns folders and spreadsheets only, which
is all either caller can use.
"""

from dataclasses import dataclass

FILES = "https://www.googleapis.com/drive/v3/files"
DRIVES = "https://www.googleapis.com/drive/v3/drives"

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"

MY_DRIVE = "root"  # what Drive calls the top of My Drive
SHARED_WITH_ME = "sharedWithMe"  # not a folder id: a query of its own
SHARED_DRIVES = "sharedDrives"  # nor is this

FIELDS = "nextPageToken, files(id, name, mimeType)"
PAGE = 200


@dataclass(frozen=True)
class DriveFile:
    """One thing in Drive: a folder to open or a spreadsheet to choose."""

    id: str
    name: str
    mime: str

    @property
    def folder(self) -> bool:
        """Whether it can be opened rather than chosen as a sheet."""
        return self.mime in (FOLDER_MIME, "drive")


class DriveError(Exception):
    """Drive would not answer. The message is what it said."""


class Drive:
    """Drive as the signed-in account sees it."""

    def __init__(self, credentials: object) -> None:
        from google.auth.transport.requests import AuthorizedSession

        self.session = AuthorizedSession(credentials)

    def listing(self, place: str) -> list[DriveFile]:
        """The folders and spreadsheets in one place, folders first and then by name."""
        if place == SHARED_DRIVES:
            return self._shared_drives()
        if place == SHARED_WITH_ME:
            found = self._files("sharedWithMe = true")
        else:
            found = self._files(f"'{place}' in parents")
        return sorted(found, key=lambda f: (not f.folder, f.name.lower()))

    def spreadsheets(self, folder_id: str) -> list[DriveFile]:
        """Every spreadsheet directly in a folder, by name."""
        found = self._files(f"'{folder_id}' in parents and mimeType = '{SHEET_MIME}'")
        return sorted(found, key=lambda f: f.name.lower())

    def file(self, file_id: str) -> DriveFile | None:
        """One file's name and kind, or None if it is gone or not shared with the account."""
        response = self.session.get(
            f"{FILES}/{file_id}",
            params={"fields": "id, name, mimeType", "supportsAllDrives": "true"},
            timeout=30,
        )
        if not response.ok:
            return None
        return _file(response.json())

    def _files(self, query: str) -> list[DriveFile]:
        """Every page of one query, trashed files left out."""
        kinds = f"(mimeType = '{FOLDER_MIME}' or mimeType = '{SHEET_MIME}')"
        params = {
            "q": f"{query} and {kinds} and trashed = false",
            "fields": FIELDS,
            "pageSize": PAGE,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "allDrives",
            "spaces": "drive",
        }
        return [_file(row) for row in self._pages(FILES, params, "files")]

    def _shared_drives(self) -> list[DriveFile]:
        """The shared drives themselves, which are browsed like folders."""
        params = {"pageSize": 100, "fields": "nextPageToken, drives(id, name)"}
        rows = self._pages(DRIVES, params, "drives")
        return sorted(
            (DriveFile(row["id"], row["name"], "drive") for row in rows),
            key=lambda f: f.name.lower(),
        )

    def _pages(self, url: str, params: dict, key: str) -> list[dict]:
        rows: list[dict] = []
        page = None
        while True:
            response = self.session.get(url, params={**params, "pageToken": page}, timeout=30)
            if not response.ok:
                raise DriveError(f"Drive: {response.status_code} {response.text[:200]}")
            body = response.json()
            rows += body.get(key, [])
            page = body.get("nextPageToken")
            if not page:
                return rows


def _file(row: dict) -> DriveFile:
    return DriveFile(row["id"], row.get("name", ""), row.get("mimeType", ""))
