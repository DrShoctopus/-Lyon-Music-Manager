"""Tests for the radio-browser.info API client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lyon.core.radio_browser import BrowseResult, RadioBrowserClient, _browse_result_from_json


# ---------------------------------------------------------------------------
# _browse_result_from_json
# ---------------------------------------------------------------------------

def test_browse_result_from_valid_json():
    item = {
        "name": "Sea Jazz FM",
        "url_resolved": "https://jazz.example.test/live",
        "tags": "jazz,smooth",
        "countrycode": "US",
        "bitrate": 128,
        "votes": 500,
    }
    result = _browse_result_from_json(item)
    assert result is not None
    assert result.station.name == "Sea Jazz FM"
    assert result.station.url == "https://jazz.example.test/live"
    assert result.station.genre == "jazz"   # first tag only
    assert result.station.bitrate == 128
    assert result.country == "US"
    assert result.votes == 500


def test_browse_result_falls_back_to_url_when_url_resolved_empty():
    item = {
        "name": "Fallback",
        "url": "https://fallback.example.test/stream",
        "url_resolved": "",
        "tags": "",
        "countrycode": "",
        "bitrate": 0,
        "votes": 0,
    }
    result = _browse_result_from_json(item)
    assert result is not None
    assert result.station.url == "https://fallback.example.test/stream"


def test_browse_result_returns_none_for_invalid_url():
    item = {"name": "Bad", "url_resolved": "not-a-url", "tags": "", "countrycode": ""}
    result = _browse_result_from_json(item)
    assert result is None


def test_browse_result_returns_none_for_non_dict():
    assert _browse_result_from_json("not a dict") is None
    assert _browse_result_from_json(None) is None


# ---------------------------------------------------------------------------
# RadioBrowserClient.search — HTTP mocked
# ---------------------------------------------------------------------------

def _fake_response(payload: list) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


_STATION_JSON = {
    "name": "Test Radio",
    "url_resolved": "https://test.example.test/live",
    "tags": "pop,rock",
    "countrycode": "GB",
    "bitrate": 192,
    "votes": 1000,
}


def test_search_parses_response():
    client = RadioBrowserClient()
    with patch("lyon.core.radio_browser.urlopen", return_value=_fake_response([_STATION_JSON])):
        results = client.search(name="Test")

    assert len(results) == 1
    assert isinstance(results[0], BrowseResult)
    assert results[0].station.name == "Test Radio"
    assert results[0].station.genre == "pop"
    assert results[0].country == "GB"
    assert results[0].votes == 1000


def test_search_caches_identical_queries():
    client = RadioBrowserClient()
    with patch("lyon.core.radio_browser.urlopen", return_value=_fake_response([_STATION_JSON])) as mock_open:
        client.search(name="Test")
        client.search(name="Test")

    assert mock_open.call_count == 1   # second call hits cache


def test_search_filters_invalid_stations():
    client = RadioBrowserClient()
    bad_item = {"name": "Bad", "url_resolved": "not-a-url", "tags": ""}
    with patch("lyon.core.radio_browser.urlopen", return_value=_fake_response([bad_item, _STATION_JSON])):
        results = client.search()

    assert len(results) == 1   # bad item filtered out


# ---------------------------------------------------------------------------
# RadioBrowserClient.list_country_codes / list_tags
# ---------------------------------------------------------------------------

def test_list_country_codes_parses_response():
    payload = [{"name": "US"}, {"name": "GB"}, {"name": "DE"}]
    client = RadioBrowserClient()
    with patch("lyon.core.radio_browser.urlopen", return_value=_fake_response(payload)):
        codes = client.list_country_codes()
    assert codes == ["US", "GB", "DE"]


def test_list_tags_parses_response():
    payload = [{"name": "jazz"}, {"name": "rock"}, {"name": ""}]
    client = RadioBrowserClient()
    with patch("lyon.core.radio_browser.urlopen", return_value=_fake_response(payload)):
        tags = client.list_tags()
    assert "jazz" in tags
    assert "rock" in tags
    assert "" not in tags   # empty name is excluded


# ---------------------------------------------------------------------------
# RadioBrowserClient.get() — singleton
# ---------------------------------------------------------------------------

def test_get_returns_same_instance():
    RadioBrowserClient._instance = None
    a = RadioBrowserClient.get()
    b = RadioBrowserClient.get()
    assert a is b
    RadioBrowserClient._instance = None   # cleanup
