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


# --- v1.0 release additions -------------------------------------------------


def test_youtube_acknowledged_defaults_false():
    s = settings.Settings()
    assert s.youtube_acknowledged is False


def test_smartscreen_advisory_shown_defaults_false():
    s = settings.Settings()
    assert s.smartscreen_advisory_shown is False


def test_youtube_acknowledged_roundtrips_through_save_load(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    s = settings.Settings(youtube_acknowledged=True)
    s.save()
    loaded = settings.Settings.load()
    assert loaded.youtube_acknowledged is True


def test_smartscreen_flag_roundtrips_through_save_load(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    s = settings.Settings(smartscreen_advisory_shown=True)
    s.save()
    loaded = settings.Settings.load()
    assert loaded.smartscreen_advisory_shown is True


def test_default_musicbrainz_contact_is_real_url():
    s = settings.Settings()
    assert s.musicbrainz_contact == settings.DEFAULT_MUSICBRAINZ_CONTACT
    assert "example" not in s.musicbrainz_contact.lower()
    assert s.musicbrainz_contact.startswith("https://")


def test_is_placeholder_contact_detects_invalid_values():
    assert settings.is_placeholder_contact("")
    assert settings.is_placeholder_contact("   ")
    assert settings.is_placeholder_contact("https://example.invalid/lyon")
    assert settings.is_placeholder_contact("http://localhost:8000/")
    assert settings.is_placeholder_contact("mailto:your-email@example.com")
    assert settings.is_placeholder_contact("mailto:your.email@test.com")


def test_is_placeholder_contact_accepts_real_values():
    assert not settings.is_placeholder_contact(
        "https://github.com/DrShoctopus/Sea-Lyon-Media-Manager"
    )
    assert not settings.is_placeholder_contact("mailto:real-user@somewhere.com")
