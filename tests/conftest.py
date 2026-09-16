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


@pytest.fixture
def dataset(source):
    return load_dataset(source, Config(), TARGET)
