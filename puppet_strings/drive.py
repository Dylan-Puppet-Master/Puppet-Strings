"""Listing Google Drive, so the Configure pane can browse it and the import can read a folder.

Almost everything here is the Drive v3 `files.list` endpoint with the flags that make shared
drives visible; there is no client library because a handful of endpoints do not need one.
Every listing is of one place — a folder, the root of My Drive, what has been shared with
the person, or the shared drives themselves — and returns folders and spreadsheets only,
which is all any caller browsing Drive can use.

`upload` is the one thing here that puts a file of its own on Drive rather than reading or
making a folder: the backup of the requests, which is neither a folder nor a spreadsheet and
so appears in none of the listings above.
"""

import json
from dataclasses import dataclass
from pathlib import Path

FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
DRIVES = "https://www.googleapis.com/drive/v3/drives"

# One boundary for every upload: it only has to be a string the file's own bytes do not
# hold, and a requests file holds no such line.
BOUNDARY = "puppet-strings-1f8b2c4e"

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"

MY_DRIVE = "root"  # what Drive calls the top of My Drive
SHARED_WITH_ME = "sharedWithMe"  # not a folder id: a query of its own
SHARED_DRIVES = "sharedDrives"  # nor is this

FIELDS = "nextPageToken, files(id, name, mimeType, version)"
PAGE = 200


@dataclass(frozen=True)
class DriveFile:
    """One thing in Drive: a folder to open or a spreadsheet to choose."""

    id: str
    name: str
    mime: str
    version: str = ""  # Drive's count of changes to it, which any edit raises; "" if not asked

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

    def child(self, parent: str, name: str, mime: str) -> DriveFile | None:
        """One named child of a folder, or None. Names in Drive are not unique; the first wins."""
        quoted = name.replace("\\", "\\\\").replace("'", "\\'")
        found = self._files(f"'{parent}' in parents and name = '{quoted}' and mimeType = '{mime}'")
        return found[0] if found else None

    def folder(self, parent: str, name: str) -> DriveFile:
        """A named folder inside another, made if it is not there yet."""
        found = self.child(parent, name, FOLDER_MIME)
        if found is not None:
            return found
        return self._make(parent, name, FOLDER_MIME)

    def spreadsheet(self, parent: str, name: str) -> DriveFile:
        """A named spreadsheet inside a folder, made if it is not there yet."""
        found = self.child(parent, name, SHEET_MIME)
        if found is not None:
            return found
        return self._make(parent, name, SHEET_MIME)

    def _make(self, parent: str, name: str, mime: str) -> DriveFile:
        """Create one thing in a folder."""
        response = self.session.post(
            FILES,
            params={"fields": "id, name, mimeType", "supportsAllDrives": "true"},
            json={"name": name, "mimeType": mime, "parents": [parent]},
            timeout=30,
        )
        if not response.ok:
            raise DriveError(f"Drive: could not make '{name}': {response.text[:200]}")
        return _file(response.json())

    def upload(self, parent: str, name: str, path: Path, mime: str) -> DriveFile:
        """Put a file from this computer into a folder, as a new file of its own.

        The metadata and the bytes go in one request, which is what Drive asks for when the
        file is small enough to send in one go; the requests file is tens of kilobytes. A
        name already in the folder is not looked for and nothing is replaced: Drive allows
        two files of one name, and a backup is one more snapshot rather than a file to keep
        up to date.
        """
        metadata = json.dumps({"name": name, "parents": [parent]})
        body = b"".join(
            (
                f"--{BOUNDARY}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
                metadata.encode(),
                f"\r\n--{BOUNDARY}\r\nContent-Type: {mime}\r\n\r\n".encode(),
                path.read_bytes(),
                f"\r\n--{BOUNDARY}--\r\n".encode(),
            )
        )
        response = self.session.post(
            UPLOAD,
            params={
                "uploadType": "multipart",
                "fields": "id, name, mimeType",
                "supportsAllDrives": "true",
            },
            data=body,
            headers={"Content-Type": f"multipart/related; boundary={BOUNDARY}"},
            timeout=60,  # a whole file, on whatever camp's connection is doing today
        )
        if not response.ok:
            raise DriveError(f"Drive: could not upload '{name}': {response.text[:200]}")
        return _file(response.json())

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
    return DriveFile(
        row["id"], row.get("name", ""), row.get("mimeType", ""), str(row.get("version", ""))
    )
