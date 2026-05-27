"""radio-browser.info REST API client."""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .radio import RadioStation, radio_user_agent, station_from_url

LOG = logging.getLogger(__name__)

_BASE_URL = "https://all.api.radio-browser.info/json"
_TIMEOUT = 10
_CACHE_SIZE = 128


@dataclass(frozen=True)
class BrowseResult:
    """A radio-browser.info search hit with display metadata."""

    station: RadioStation
    country: str = ""
    votes: int = 0


class RadioBrowserClient:
    """Thin wrapper around the radio-browser.info REST API.

    Instantiate via ``RadioBrowserClient.get()`` to reuse the singleton and
    its in-memory search cache across the app.  Import cost is zero; the
    singleton is only created on first use.
    """

    _instance: RadioBrowserClient | None = None

    @classmethod
    def get(cls) -> RadioBrowserClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._search_cache: OrderedDict[tuple, list[RadioStation]] = OrderedDict()

    # ------------------------------------------------------------------ public

    def search(
        self,
        *,
        name: str = "",
        tag: str = "",
        country: str = "",
        limit: int = 100,
    ) -> list[BrowseResult]:
        key = (name.casefold(), tag.casefold(), country.upper(), limit)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        params: dict[str, str] = {
            "limit": str(limit),
            "hidebroken": "true",
            "order": "votes",
            "reverse": "true",
        }
        if name:
            params["name"] = name
        if tag:
            params["tag"] = tag
        if country:
            params["countrycode"] = country

        data = self._get("stations/search", params)
        result = [r for item in data if (r := _browse_result_from_json(item)) is not None]
        self._cache_put(key, result)
        return result

    def by_uuid(self, uuid: str) -> RadioStation | None:
        data = self._get(f"stations/byuuid/{uuid}")
        if isinstance(data, list) and data:
            return _station_from_json(data[0])
        return None

    def list_country_codes(self) -> list[str]:
        data = self._get("countrycodes", {
            "order": "stationcount", "reverse": "true", "limit": "500",
        })
        return [
            str(item["name"])
            for item in data
            if isinstance(item, dict) and item.get("name")
        ]

    def list_tags(self, limit: int = 200) -> list[str]:
        data = self._get("tags", {
            "order": "stationcount",
            "reverse": "true",
            "limit": str(limit),
            "hidebroken": "true",
        })
        return [
            str(item["name"])
            for item in data
            if isinstance(item, dict) and item.get("name")
        ]

    # ------------------------------------------------------------------ private

    def _get(self, path: str, params: dict[str, str] | None = None) -> list:
        url = f"{_BASE_URL}/{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        req = Request(url, headers={
            "User-Agent": radio_user_agent(),
            "Accept": "application/json",
        })
        with urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list):
            return []
        return data

    def _cache_get(self, key: tuple) -> list[RadioStation] | None:
        if key not in self._search_cache:
            return None
        self._search_cache.move_to_end(key)
        return self._search_cache[key]

    def _cache_put(self, key: tuple, value: list[RadioStation]) -> None:
        self._search_cache[key] = value
        self._search_cache.move_to_end(key)
        while len(self._search_cache) > _CACHE_SIZE:
            self._search_cache.popitem(last=False)


def _browse_result_from_json(item: object) -> BrowseResult | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url_resolved") or item.get("url") or "").strip()
    name = str(item.get("name") or "").strip()
    tags_raw = str(item.get("tags") or "").strip()
    genre = tags_raw.split(",")[0].strip() if tags_raw else ""
    bitrate = _safe_int(item.get("bitrate"))
    station = station_from_url(url, name=name, genre=genre, bitrate=bitrate)
    if station is None:
        return None
    country = str(item.get("countrycode") or "").strip().upper()
    votes = _safe_int(item.get("votes"))
    return BrowseResult(station=station, country=country, votes=votes)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
