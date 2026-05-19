from __future__ import annotations

from lyon.core.radio import parse_playlist_file, parse_playlist_text, station_from_url
from lyon.core.settings import Settings, normalize_radio_stations


def test_parse_m3u_reads_extinf_genre_and_url():
    stations = parse_playlist_text(
        "#EXTM3U\n"
        "#EXTGRP:Jazz\n"
        "#EXTINF:-1,Sea Lyon Jazz\n"
        "https://radio.example.test/jazz\n"
    )

    assert len(stations) == 1
    assert stations[0].name == "Sea Lyon Jazz"
    assert stations[0].genre == "Jazz"
    assert stations[0].url == "https://radio.example.test/jazz"


def test_parse_pls_reads_titles_bitrates_and_dedupes():
    stations = parse_playlist_text(
        "[playlist]\n"
        "File1=https://radio.example.test/live\n"
        "Title1=Sea Lyon Radio\n"
        "Bitrate1=192\n"
        "File2=https://radio.example.test/live\n"
        "Title2=Duplicate\n"
    )

    assert len(stations) == 1
    assert stations[0].name == "Sea Lyon Radio"
    assert stations[0].bitrate == 192


def test_parse_hls_variant_playlist_resolves_relative_urls():
    stations = parse_playlist_text(
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=128000\n"
        "low/index.m3u8\n",
        base_url="https://radio.example.test/master.m3u8",
        default_name="Master",
    )

    assert stations[0].url == "https://radio.example.test/low/index.m3u8"
    assert stations[0].name == "Master"
    assert stations[0].bitrate == 128


def test_parse_playlist_file_uses_file_stem_as_default_name(tmp_path):
    playlist = tmp_path / "Morning.m3u"
    playlist.write_text("https://radio.example.test/morning\n", encoding="utf-8")

    stations = parse_playlist_file(playlist)

    assert stations[0].name == "Morning"


def test_station_from_url_rejects_non_stream_urls():
    assert station_from_url("file:///tmp/song.flac") is None
    assert station_from_url("https://radio.example.test/live").name == "radio.example.test / live"


def test_radio_station_settings_normalize_and_merge():
    settings = Settings(
        radio_stations=[
            {"name": "One", "url": "https://one.example.test/live", "bitrate": "128"},
            {"name": "Bad", "url": "file:///tmp/song.flac"},
        ]
    )

    settings.add_radio_stations([
        {"name": "One Updated", "url": "https://one.example.test/live", "genre": "News"},
        {"name": "Two", "url": "https://two.example.test/live"},
    ])

    assert normalize_radio_stations("bad") == []
    assert settings.radio_stations == [
        {"name": "One Updated", "url": "https://one.example.test/live", "genre": "News", "bitrate": 0},
        {"name": "Two", "url": "https://two.example.test/live", "genre": "", "bitrate": 0},
    ]
