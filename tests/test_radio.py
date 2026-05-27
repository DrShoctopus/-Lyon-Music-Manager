from __future__ import annotations

from lyon.core.radio import (
    parse_playlist_file,
    parse_playlist_text,
    parse_stream_title,
    station_from_url,
    stations_to_m3u,
    stations_to_pls,
)
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


def test_parse_extinf_duration_is_not_treated_as_bitrate():
    stations = parse_playlist_text(
        "#EXTM3U\n"
        "#EXTINF:300,Sea Lyon Live\n"
        "https://radio.example.test/live\n"
    )

    assert stations[0].bitrate == 0


def test_parse_extinf_reads_bitrate_attribute():
    stations = parse_playlist_text(
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-id="lyon" bitrate="192",Sea Lyon HQ\n'
        "https://radio.example.test/hq\n"
    )

    assert stations[0].name == "Sea Lyon HQ"
    assert stations[0].bitrate == 192


def test_parse_extinf_respects_quoted_commas_in_attributes():
    stations = parse_playlist_text(
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-name="Lyon, Live",Sea Lyon Live\n'
        "https://radio.example.test/live\n"
    )

    assert stations[0].name == "Sea Lyon Live"


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
    # Bitrate from the original "One" entry is preserved because the update
    # left bitrate blank — see Settings.add_radio_stations.
    assert settings.radio_stations == [
        {"name": "One Updated", "url": "https://one.example.test/live", "genre": "News", "bitrate": 128, "favorite": False, "tags": []},
        {"name": "Two", "url": "https://two.example.test/live", "genre": "", "bitrate": 0, "favorite": False, "tags": []},
    ]


# ---- parse_stream_title (ICY metadata helper) -------------------------------

def test_parse_stream_title_splits_artist_and_title():
    assert parse_stream_title("Daft Punk - One More Time") == ("Daft Punk", "One More Time")


def test_parse_stream_title_strips_whitespace():
    assert parse_stream_title("  Daft Punk  -  One More Time  ") == ("Daft Punk", "One More Time")


def test_parse_stream_title_uses_first_separator_only():
    # Real ICY values often contain extra dashes inside the song title —
    # only the first " - " should split artist from the rest.
    assert parse_stream_title("Artist - Song - Live Version") == (
        "Artist",
        "Song - Live Version",
    )


def test_parse_stream_title_without_separator_returns_title_only():
    assert parse_stream_title("Just A Song Title") == ("", "Just A Song Title")


def test_parse_stream_title_empty_returns_empty_pair():
    assert parse_stream_title("") == ("", "")
    assert parse_stream_title("   ") == ("", "")


def test_parse_stream_title_leading_dash_kept_when_no_real_separator():
    # The leading "- " is not " - " (space-dash-space) once whitespace is
    # stripped, so we conservatively treat the whole thing as a title rather
    # than guess at the broadcaster's intent.
    assert parse_stream_title(" - Title Only") == ("", "- Title Only")


def _two_stations():
    return [
        station_from_url("https://jazz.example.test/live", name="Sea Jazz", genre="Jazz", bitrate=128),
        station_from_url("https://news.example.test/live", name="Sea News"),
    ]


def test_stations_to_m3u_round_trips_via_parse():
    stations = _two_stations()
    m3u = stations_to_m3u(stations)
    assert m3u.startswith("#EXTM3U")
    result = parse_playlist_text(m3u)
    assert len(result) == 2
    assert result[0].url == "https://jazz.example.test/live"
    assert result[0].name == "Sea Jazz"
    assert result[1].url == "https://news.example.test/live"
    assert result[1].name == "Sea News"


def test_stations_to_pls_round_trips_via_parse():
    stations = _two_stations()
    pls = stations_to_pls(stations)
    assert pls.startswith("[playlist]")
    result = parse_playlist_text(pls)
    assert len(result) == 2
    assert result[0].url == "https://jazz.example.test/live"
    assert result[0].name == "Sea Jazz"
    assert result[1].url == "https://news.example.test/live"
    assert result[1].name == "Sea News"


def test_stations_to_m3u_empty_list():
    assert stations_to_m3u([]) == "#EXTM3U"


def test_stations_to_pls_empty_list():
    pls = stations_to_pls([])
    assert "[playlist]" in pls
    assert "NumberOfEntries=0" in pls


# ---- Favorites & Tags (PR4) -------------------------------------------------

def test_station_from_url_accepts_favorite_and_tags():
    s = station_from_url(
        "https://radio.example.test/live",
        name="Test",
        tags=("jazz", "smooth"),
        favorite=True,
    )
    assert s is not None
    assert s.favorite is True
    assert s.tags == ("jazz", "smooth")


def test_station_from_settings_parses_favorite_and_tags():
    from lyon.core.radio import station_from_settings
    s = station_from_settings({
        "name": "Fav",
        "url": "https://radio.example.test/live",
        "favorite": True,
        "tags": ["jazz", "smooth"],
    })
    assert s is not None
    assert s.favorite is True
    assert s.tags == ("jazz", "smooth")


def test_station_from_settings_defaults_favorite_false():
    from lyon.core.radio import station_from_settings
    s = station_from_settings({"name": "X", "url": "https://radio.example.test/live"})
    assert s is not None
    assert s.favorite is False
    assert s.tags == ()


def test_station_from_settings_parses_tags_as_comma_string():
    from lyon.core.radio import station_from_settings
    s = station_from_settings({
        "name": "X",
        "url": "https://radio.example.test/live",
        "tags": "jazz, smooth",
    })
    assert s is not None
    assert s.tags == ("jazz", "smooth")


def test_as_settings_dict_includes_favorite_and_tags():
    s = station_from_url(
        "https://radio.example.test/live",
        name="X",
        tags=("jazz",),
        favorite=True,
    )
    assert s is not None
    d = s.as_settings_dict()
    assert d["favorite"] is True
    assert d["tags"] == ["jazz"]


def test_normalize_radio_stations_preserves_favorite_and_tags():
    from lyon.core.settings import normalize_radio_stations
    result = normalize_radio_stations([{
        "name": "X",
        "url": "https://radio.example.test/live",
        "favorite": True,
        "tags": ["jazz", "smooth"],
    }])
    assert result[0]["favorite"] is True
    assert result[0]["tags"] == ["jazz", "smooth"]
