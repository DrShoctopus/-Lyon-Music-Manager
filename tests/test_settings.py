from lyon.core import settings


def test_settings_load_returns_defaults_when_read_fails(monkeypatch, tmp_path):
    (tmp_path / "settings.json").mkdir()
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)

    loaded = settings.Settings.load()

    assert isinstance(loaded, settings.Settings)
    assert not hasattr(loaded, "_corrupt_backup_path")
