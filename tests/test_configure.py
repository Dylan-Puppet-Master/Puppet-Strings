"""The Configure pane and the Drive browser, against a Drive that is only a dict."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from puppet_strings.app.configure import NOT_CHOSEN, ConfigureDialog  # noqa: E402
from puppet_strings.app.drive_browser import DriveBrowser  # noqa: E402
from puppet_strings.config import Config  # noqa: E402
from puppet_strings.drive import (  # noqa: E402
    FOLDER_MIME,
    MY_DRIVE,
    SHARED_DRIVES,
    SHARED_WITH_ME,
    SHEET_MIME,
    DriveError,
    DriveFile,
)
from puppet_strings.settings import Chosen, load_settings  # noqa: E402


class FakeDrive:
    """Three places and two folders, enough to walk into one and choose what is inside."""

    TREE = {
        MY_DRIVE: [DriveFile("f1", "Camp", FOLDER_MIME), DriveFile("s1", "Config", SHEET_MIME)],
        SHARED_WITH_ME: [DriveFile("f2", "Cabin Act Testing", FOLDER_MIME)],
        SHARED_DRIVES: [DriveFile("d1", "Programme", "drive")],
        "f1": [DriveFile("s2", "Skills", SHEET_MIME)],
        "f2": [DriveFile("s3", "Cabin Act Sorting - S5W1", SHEET_MIME)],
        "d1": [],
    }

    def listing(self, place):
        if place not in self.TREE:
            raise DriveError("no such folder")
        return self.TREE[place]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("PUPPET_STRINGS_SETTINGS", str(tmp_path / "settings.json"))
    return Config(token=tmp_path / "token.json", client_secrets=tmp_path / "client.json")


def browser(want_folder=False):
    found = DriveBrowser(FakeDrive(), want_folder=want_folder)
    found.wait_for_listing()
    return found


def test_the_browser_opens_on_my_drive(app):
    found = browser()
    assert found.crumbs.text() == "My Drive"
    assert [found.listing.item(r).text() for r in range(found.listing.count())] == [
        "📁  Camp",
        "📄  Config",
    ]
    assert not found.up_button.isEnabled()


def test_every_place_drive_offers_is_listed(app):
    found = browser()
    for row, expected in enumerate(("My Drive", "Shared with me", "Shared drives")):
        found.places.setCurrentRow(row)
        found.wait_for_listing()
        assert found.crumbs.text() == expected
    assert found.listing.item(0).text() == "📁  Programme"


def test_opening_a_folder_and_coming_back_up(app):
    found = browser()
    found.open_folder(DriveFile("f1", "Camp", FOLDER_MIME))
    found.wait_for_listing()
    assert found.crumbs.text() == "My Drive / Camp"
    assert found.up_button.isEnabled()
    found.go_up()
    found.wait_for_listing()
    assert found.crumbs.text() == "My Drive"


def test_only_a_spreadsheet_can_be_chosen_when_one_is_wanted(app):
    found = browser()
    found.listing.setCurrentRow(0)  # the Camp folder
    assert found.selection is None and not found.select_button.isEnabled()
    found.listing.setCurrentRow(1)  # the Config sheet
    assert found.selection.id == "s1" and found.select_button.isEnabled()


def test_a_folder_is_chosen_by_standing_in_it_or_picking_it(app):
    found = browser(want_folder=True)
    assert found.selection is None  # a root is not a folder to read sheets from
    found.listing.setCurrentRow(0)
    assert found.selection.id == "f1"
    found.open_folder(DriveFile("f1", "Camp", FOLDER_MIME))
    found.wait_for_listing()
    assert found.selection.id == "f1"  # standing in it is choosing it


def test_a_folder_that_cannot_be_listed_says_so(app):
    found = browser()
    found.open_folder(DriveFile("gone", "Gone", FOLDER_MIME))
    found.wait_for_listing()
    assert "Could not list" in found.listing.item(0).text()


def test_the_pane_asks_for_two_folders_and_nothing_else(app, config):
    """Everything inside the Puppet Strings folder is found by name, so nothing else is asked."""
    dialog = ConfigureDialog(config, credentials=object())
    assert sorted(dialog.rows) == [("folders", "cabin_acts"), ("folders", "root")]


def test_the_pane_shows_what_is_chosen_and_saves_it(app, config):
    dialog = ConfigureDialog(config, credentials=object())
    assert dialog.rows["folders", "root"].text() == NOT_CHOSEN
    dialog.choose("folders", "root", Chosen("abc", "Puppet Strings"))
    dialog.choose("folders", "cabin_acts", Chosen("f2", "Cabin Act Testing"))
    assert dialog.rows["folders", "root"].text() == "Puppet Strings"
    dialog.save()
    saved = load_settings()
    assert saved.folders["root"] == Chosen("abc", "Puppet Strings")
    assert saved.folders["cabin_acts"] == Chosen("f2", "Cabin Act Testing")


def test_clearing_a_choice_forgets_it(app, config):
    dialog = ConfigureDialog(config, credentials=object())
    dialog.choose("folders", "root", Chosen("abc", "Puppet Strings"))
    dialog.clear("folders", "root")
    assert dialog.rows["folders", "root"].text() == NOT_CHOSEN
    dialog.save()
    assert "root" not in load_settings().folders


def test_nothing_is_written_until_save(app, config):
    dialog = ConfigureDialog(config, credentials=object())
    dialog.choose("folders", "root", Chosen("abc", "Puppet Strings"))
    dialog.reject()
    assert load_settings().folders == {}


def test_the_pane_says_when_nobody_is_signed_in(app, config):
    dialog = ConfigureDialog(config, credentials=None)
    assert dialog.account_label.text() == "Not signed in"
    assert not dialog.sign_out_button.isEnabled()
    assert dialog.sign_in_button.text() == "Sign in"


def test_signing_out_forgets_the_token(app, config):
    config.token.write_text("{}")
    dialog = ConfigureDialog(config, credentials=object())
    assert dialog.sign_out_button.isEnabled()
    dialog.sign_out()
    assert not config.token.exists()
    assert dialog.account_label.text() == "Not signed in"
    assert dialog.saved  # the window must read everything again


def test_the_pane_has_no_empty_spreadsheets_box(app, config):
    """Nothing is chosen sheet by sheet any more, so there is no box for it."""
    from PySide6.QtWidgets import QGroupBox

    dialog = ConfigureDialog(config, credentials=object())
    assert [box.title() for box in dialog.findChildren(QGroupBox)] == [
        "Google account",
        "Directories",
        "Version",
    ]
    assert dialog.updates_button.text() == "Check for updates"
