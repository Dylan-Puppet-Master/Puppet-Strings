"""Looking for a newer Puppet Strings: what is offered, and what is not."""

import pytest

from puppet_strings import __version__
from puppet_strings.update import Release, UpdateError, install, is_newer, latest_release


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("1.0.0", "0.9.9", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("v0.2.0", "0.1.0", True),
    ],
)
def test_version_comparison(candidate, current, newer):
    assert is_newer(candidate, current) is newer


def _release(monkeypatch, payload):
    monkeypatch.setattr("puppet_strings.update.requests.get", lambda *a, **k: Response(payload))
    return latest_release("https://example.invalid/releases/latest")


def test_a_newer_release_for_this_platform_is_offered(monkeypatch):
    monkeypatch.setattr("puppet_strings.update.sys.platform", "linux")
    release = _release(
        monkeypatch,
        {
            "tag_name": "v9.9.9",
            "body": "Quicker loads",
            "assets": [
                {"name": "puppet-strings-windows.exe", "browser_download_url": "https://w"},
                {"name": "puppet-strings-linux", "browser_download_url": "https://l"},
            ],
        },
    )
    assert release == Release("9.9.9", "https://l", "Quicker loads")


def test_the_current_version_is_not_offered(monkeypatch):
    payload = {
        "tag_name": f"v{__version__}",
        "assets": [{"name": "puppet-strings-linux", "browser_download_url": "https://l"}],
    }
    assert _release(monkeypatch, payload) is None


def test_a_release_without_a_file_for_this_platform_is_not_offered(monkeypatch):
    monkeypatch.setattr("puppet_strings.update.sys.platform", "linux")
    payload = {"tag_name": "v9.9.9", "assets": [{"name": "puppet-strings-windows.exe"}]}
    assert _release(monkeypatch, payload) is None


def test_a_failed_check_says_so_rather_than_raising_something_raw(monkeypatch):
    def explode(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr("puppet_strings.update.requests.get", explode)
    with pytest.raises(UpdateError, match="Could not check for updates"):
        latest_release("https://example.invalid/releases/latest")


def test_installing_over_a_source_checkout_is_refused(tmp_path):
    with pytest.raises(UpdateError, match="from source"):
        install(tmp_path / "downloaded")
