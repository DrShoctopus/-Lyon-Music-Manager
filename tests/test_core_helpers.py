from pathlib import Path

from lyon.core import ffmpeg, user_agent
from lyon.core.settings import Settings


def test_find_ffmpeg_binary_prefers_bundled_binary(monkeypatch, tmp_path):
    bundled = tmp_path / "bin"
    bundled.mkdir()
    binary = bundled / "ffmpeg"
    binary.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(ffmpeg, "bundled_bin_dir", lambda: bundled)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    assert ffmpeg.find_ffmpeg_binary() == binary


def test_find_ffmpeg_binary_falls_back_to_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ffmpeg, "bundled_bin_dir", lambda: tmp_path)
    monkeypatch.setattr(
        ffmpeg.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )

    assert ffmpeg.find_ffmpeg_binary() == Path("/usr/bin/ffmpeg")


def test_component_user_agent_uses_default_contact_when_settings_contact_blank():
    ua = user_agent.component_user_agent("Podcast", Settings(musicbrainz_contact=" "))

    assert ua.startswith("Sea Lyon Media Manager/")
    assert "(+https://github.com/DrShoctopus/Sea-Lyon-Media-Manager)" in ua
    assert ua.endswith(" Podcast/1.0")


def test_musicbrainz_user_agent_uses_settings_identity():
    ua = user_agent.musicbrainz_user_agent(
        Settings(
            musicbrainz_app="App",
            musicbrainz_version="2.3",
            musicbrainz_contact="real@example.test",
        )
    )

    assert ua == "App/2.3 (real@example.test)"
