import shutil
from datetime import date
from pathlib import Path

import pytest

from puppet_strings.config import Config
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.source import CsvSource

FIXTURES = Path(__file__).parent / "fixtures"
TARGET = date(2026, 9, 16)


@pytest.fixture
def source() -> CsvSource:
    return CsvSource(FIXTURES)


CONFIG = Config(folders={"schedules": "schedules", "cabin_acts": "cabin_acts"})


@pytest.fixture
def dataset(source):
    return load_dataset(source, CONFIG, TARGET)


@pytest.fixture
def fixtures_copy(tmp_path) -> Path:
    """A copy of the fixture sheets that a test may write to."""
    copy = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, copy)
    return copy
