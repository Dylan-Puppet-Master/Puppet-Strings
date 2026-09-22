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


def linux_package(tmp_path, executable="puppet-strings-linux", icon=True):
    """A tar.gz shaped like the Linux release: the program, its icon and install.sh."""
    import tarfile

    package = tmp_path / "package"
    package.mkdir()
    (package / executable).write_text("#!/bin/sh\necho new\n")
    (package / "install.sh").write_text("#!/bin/sh\n")
    if icon:
        (package / "puppet-strings.png").write_bytes(b"new icon")
    archive = tmp_path / "puppet-strings-linux.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(package, arcname="puppet-strings-linux")
    return archive


def installed(tmp_path, monkeypatch, icon=True):
    """A copy of the program installed in a folder, as install.sh leaves it."""
    home = tmp_path / "opt"
    home.mkdir()
    running = home / "puppet-strings-linux"
    running.write_text("old")
    if icon:
        (home / "puppet-strings.png").write_bytes(b"old icon")
    monkeypatch.setattr("puppet_strings.update.sys.frozen", True, raising=False)
    monkeypatch.setattr("puppet_strings.update.sys.executable", str(running))
    return running


def test_a_linux_release_is_unpacked_and_the_program_inside_it_installed(tmp_path, monkeypatch):
    """The Linux release is a tar.gz; moving that over the executable would be the end of it."""
    running = installed(tmp_path, monkeypatch)
    where = install(linux_package(tmp_path))
    assert where == running
    assert running.read_text() == "#!/bin/sh\necho new\n"
    assert running.stat().st_mode & 0o111  # and it can still be run
    assert (running.with_name("puppet-strings-linux.old")).read_text() == "old"
    assert (running.parent / "puppet-strings.png").read_bytes() == b"new icon"
    assert not (running.parent / "install.sh").exists()  # nothing else is unpacked into place


def test_an_icon_is_only_refreshed_where_there_is_one(tmp_path, monkeypatch):
    """A copy run out of a downloads folder has no desktop entry and no use for a picture."""
    running = installed(tmp_path, monkeypatch, icon=False)
    install(linux_package(tmp_path))
    assert not (running.parent / "puppet-strings.png").exists()


def test_a_bare_executable_is_still_installed_as_it_was(tmp_path, monkeypatch):
    """Windows and macOS release one file, which is the whole of the update."""
    running = installed(tmp_path, monkeypatch, icon=False)
    downloaded = tmp_path / "puppet-strings-macos"
    downloaded.write_text("new")
    assert install(downloaded) == running
    assert running.read_text() == "new"


def test_an_archive_with_no_program_in_it_says_so(tmp_path, monkeypatch):
    installed(tmp_path, monkeypatch)
    archive = linux_package(tmp_path, executable="readme.txt", icon=False)
    with pytest.raises(UpdateError, match="holds no puppet-strings-linux"):
        install(archive)
