from puppet_strings.config import load_config
from puppet_strings.settings import Chosen, Settings, load_settings, save_settings


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(
        sheets={"config": Chosen("abc", "Puppet Strings Config")},
        folders={"cabin_acts": Chosen("def", "Cabin Act Testing")},
    )
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert load_settings(path).ids("sheets") == {"config": "abc"}


def test_a_missing_or_broken_file_means_nothing_chosen(tmp_path):
    assert load_settings(tmp_path / "gone.json") == Settings()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert load_settings(broken) == Settings()


def test_chosen_sheets_win_over_the_config_file(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('[sheets]\nconfig = "old"\nskills = "kept"\n')
    chosen = tmp_path / "settings.json"
    save_settings(Settings(sheets={"config": Chosen("new", "Config")}), chosen)
    monkeypatch.setenv("PUPPET_STRINGS_SETTINGS", str(chosen))
    loaded = load_config(config)
    assert loaded.sheets == {"config": "new", "skills": "kept"}


def test_no_config_file_still_reads_the_choices(tmp_path, monkeypatch):
    chosen = tmp_path / "settings.json"
    save_settings(Settings(folders={"cabin_acts": Chosen("f1", "Cabin Acts")}), chosen)
    monkeypatch.setenv("PUPPET_STRINGS_SETTINGS", str(chosen))
    assert load_config(tmp_path / "none.toml").folders == {"cabin_acts": "f1"}


def test_the_token_is_never_readable_by_anybody_else(tmp_path):
    """It holds a refresh token that is good until somebody revokes it."""
    import os
    import stat

    from puppet_strings.google_auth import _write

    class Credentials:
        def to_json(self):
            return '{"refresh_token": "secret"}'

    token = tmp_path / "token.json"
    umask = os.umask(0o000)  # the permissive umask the file has to survive
    try:
        _write(token, Credentials())
    finally:
        os.umask(umask)
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert token.read_text() == '{"refresh_token": "secret"}'
