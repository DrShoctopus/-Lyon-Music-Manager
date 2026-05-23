from lyon.core import settings


def test_tests_use_isolated_app_data_dir(tmp_path):
    from lyon.core import library

    expected = tmp_path / "app-data"

    assert settings.app_data_dir() == expected
    assert library.app_data_dir() == expected


def test_settings_load_returns_defaults_when_read_fails(monkeypatch, tmp_path):
    (tmp_path / "settings.json").mkdir()
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)

    loaded = settings.Settings.load()

    assert isinstance(loaded, settings.Settings)
    assert not hasattr(loaded, "_corrupt_backup_path")


def test_settings_save_uses_owner_only_permissions(monkeypatch, tmp_path):
    import os
    import stat

    if os.name == "nt":
        return
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)

    settings.Settings(listenbrainz_token="secret").save()

    mode = stat.S_IMODE((tmp_path / "settings.json").stat().st_mode)
    assert mode == 0o600
