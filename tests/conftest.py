import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from puppet_strings.config import Config
from puppet_strings.model import Request
from puppet_strings.requests_db import FIXTURE_FILE, RequestDb
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.source import CsvSource

FIXTURES = Path(__file__).parent / "fixtures"
TARGET = date(2026, 9, 16)


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    """No test reads or writes the settings or config file of whoever runs the tests.

    A group's default scope, the chosen folders and every other choice made in the app are
    kept there; a test that saves one would change the Puppet Master's own.
    """
    monkeypatch.setenv("PUPPET_STRINGS_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("PUPPET_STRINGS_CONFIG", str(tmp_path / "config.toml"))


@pytest.fixture
def source() -> CsvSource:
    return CsvSource(FIXTURES)


CONFIG = Config(folders={"root": "root", "cabin_acts": "cabin_acts"})


@pytest.fixture
def dataset(source):
    return load_dataset(source, CONFIG, TARGET)


@pytest.fixture
def fixtures_copy(tmp_path) -> Path:
    """A copy of the fixture sheets that a test may write to."""
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    return copy


def saved_requests(folder: Path) -> dict[str, Request]:
    """What a fixture folder's requests file holds, by id."""
    return {r.id: r for r in RequestDb(folder / FIXTURE_FILE).every()}


def delete_requests(folder: Path, where: str, *args) -> None:
    """Take rows out of a fixture folder's requests file, as another program might."""
    with sqlite3.connect(folder / FIXTURE_FILE) as db:
        db.execute(f"DELETE FROM requests WHERE {where}", args)
