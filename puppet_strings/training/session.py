"""The session the trainer practises on: a CSV copy of a real one, bundled with the app.

`tools/snapshot_training.py` makes the copy. Nothing here reaches Google: the whole point is
that a new Puppet Master can practise on a train, and cannot break a real schedule doing it.
"""

from datetime import date
from pathlib import Path
from threading import Lock

from puppet_strings.config import Config
from puppet_strings.model import Dataset
from puppet_strings.sheets.load import CABIN_ACTS_FOLDER, load_dataset
from puppet_strings.sheets.schedules import ROOT
from puppet_strings.sheets.source import CsvSource

DATA = Path(__file__).parent / "data"
CONFIG = Config(folders={ROOT: ROOT, CABIN_ACTS_FOLDER: CABIN_ACTS_FOLDER})

_loaded: dict[date, Dataset] = {}
_loading = Lock()  # the window and a check running beside it may both ask for a day


def dataset(day: date) -> Dataset:
    """The session as it stood on one of its days. Loaded once per day and kept."""
    with _loading:
        if day not in _loaded:
            _loaded[day] = load_dataset(CsvSource(DATA), CONFIG, day, history=False)
        return _loaded[day]
