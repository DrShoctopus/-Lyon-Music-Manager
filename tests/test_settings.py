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
    assert loaded.corrupt_backup_path == ""


def test_settings_load_records_corrupt_backup_path_without_saving_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text("{bad json", encoding="utf-8")

    loaded = settings.Settings.load()
    loaded.save()
    saved = (tmp_path / "settings.json").read_text(encoding="utf-8")

    assert loaded.corrupt_backup_path == str(tmp_path / "settings.json.bad")
    assert "corrupt_backup_path" not in saved


def test_settings_load_ignores_transient_corrupt_backup_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"music_root": "/music", "corrupt_backup_path": "/tmp/stale"}',
        encoding="utf-8",
    )

    loaded = settings.Settings.load()

    assert loaded.music_root == "/music"
    assert loaded.corrupt_backup_path == ""


def test_settings_save_uses_owner_only_permissions(monkeypatch, tmp_path):
    import os
    import stat

    if os.name == "nt":
        return
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)

    settings.Settings(listenbrainz_token="secret").save()

    mode = stat.S_IMODE((tmp_path / "settings.json").stat().st_mode)
    assert mode == 0o600


def test_settings_cache_loads_under_module_lock(monkeypatch):
    settings.invalidate_settings_cache()
    observed: list[bool] = []

    def fake_load():
        observed.append(settings._settings_cache_lock.locked())
        return settings.Settings(music_root="/cached")

    monkeypatch.setattr(settings.Settings, "load", staticmethod(fake_load))

    cached = settings.get_cached_settings()

    assert cached.music_root == "/cached"
    assert observed == [True]


# --- v1.0 release additions -------------------------------------------------


def test_youtube_acknowledged_defaults_false():
    s = settings.Settings()
    assert s.youtube_acknowledged is False


def test_youtube_browser_cookies_defaults_to_disabled_firefox():
    s = settings.Settings()
    assert s.yt_use_browser_cookies is False
    assert s.yt_browser_cookies_browser == "firefox"


def test_youtube_browser_cookies_roundtrips_through_save_load(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    s = settings.Settings(
        yt_use_browser_cookies=True,
        yt_browser_cookies_browser="chrome",
    )
    s.save()

    loaded = settings.Settings.load()

    assert loaded.yt_use_browser_cookies is True
    assert loaded.yt_browser_cookies_browser == "chrome"


def test_youtube_browser_cookies_browser_is_normalized():
    s = settings.Settings(yt_use_browser_cookies=True, yt_browser_cookies_browser="not-a-browser")
    assert s.yt_browser_cookies_browser == "firefox"


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


def test_dlna_bind_address_defaults_to_all_interfaces():
    s = settings.Settings()
    assert s.dlna_bind_address == "0.0.0.0"


def test_dlna_bind_address_roundtrips_through_save_load(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    s = settings.Settings(dlna_bind_address="127.0.0.1")
    s.save()
    loaded = settings.Settings.load()
    assert loaded.dlna_bind_address == "127.0.0.1"


def test_default_musicbrainz_contact_is_real_url():
    s = settings.Settings()
    assert s.musicbrainz_contact == settings.DEFAULT_MUSICBRAINZ_CONTACT
    assert "example" not in s.musicbrainz_contact.lower()
    assert s.musicbrainz_contact.startswith("https://")


def test_default_theaudiodb_key_uses_free_tier():
    s = settings.Settings()
    assert s.theaudiodb_api_key == settings.DEFAULT_THEAUDIODB_API_KEY


def test_legacy_blank_theaudiodb_key_migrates_to_default(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"music_root": "/music", "theaudiodb_api_key": ""}',
        encoding="utf-8",
    )

    loaded = settings.Settings.load()

    assert loaded.theaudiodb_api_key == settings.DEFAULT_THEAUDIODB_API_KEY
    assert loaded.theaudiodb_api_key_opt_out is False


def test_explicit_blank_theaudiodb_key_opt_out_roundtrips(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", lambda: tmp_path)
    s = settings.Settings(theaudiodb_api_key="", theaudiodb_api_key_opt_out=True)
    s.save()

    loaded = settings.Settings.load()

    assert loaded.theaudiodb_api_key == ""
    assert loaded.theaudiodb_api_key_opt_out is True


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
