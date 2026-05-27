"""Internet radio station and playlist parsing helpers."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .settings import normalize_stream_urls

_HEAD_THEN_GET = ("HEAD", "GET")


def radio_user_agent() -> str:
    """Return a Sea Lyon UA string for outbound radio stream requests."""
    from .settings import Settings, get_cached_settings
    from .user_agent import component_user_agent

    try:
        settings = get_cached_settings()
    except Exception:  # noqa: BLE001 — UA must never crash a stream start
        settings = Settings()
    return component_user_agent("Radio", settings)


def parse_stream_title(text: str) -> tuple[str, str]:
    """Split an ICY ``StreamTitle`` value into ``(artist, title)``.

    The dominant convention encoded in ``StreamTitle`` is ``"Artist - Title"``,
    so we split on the first ``" - "`` separator. Anything without a separator
    is treated as a title with no artist.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return "", ""
    separator = " - "
    index = cleaned.find(separator)
    if index <= 0:
        return "", cleaned
    artist = cleaned[:index].strip()
    title = cleaned[index + len(separator):].strip()
    if not title:
        return "", artist
    return artist, title


@dataclass(frozen=True)
class RadioStation:
    name: str
    url: str
    genre: str = ""
    bitrate: int = 0
    favorite: bool = False
    tags: tuple[str, ...] = ()

    def as_settings_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "genre": self.genre,
            "bitrate": self.bitrate,
            "favorite": self.favorite,
            "tags": list(self.tags),
        }


def parse_playlist_text(text: str, *, base_url: str = "", default_name: str = "") -> list[RadioStation]:
    """Parse M3U, PLS, or HLS text into radio station candidates."""
    stripped = text.lstrip()
    if stripped.casefold().startswith("[playlist]"):
        return _parse_pls(text, base_url=base_url)
    return _parse_m3u(text, base_url=base_url, default_name=default_name)


def parse_playlist_file(path: str | Path) -> list[RadioStation]:
    playlist_path = Path(path)
    data = playlist_path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_playlist_text(data, default_name=playlist_path.stem)


def station_from_url(
    url: str,
    *,
    name: str = "",
    genre: str = "",
    bitrate: int = 0,
    tags: tuple[str, ...] = (),
    favorite: bool = False,
) -> RadioStation | None:
    clean_url = _clean_url(url)
    if not normalize_stream_urls([clean_url]):
        return None
    return RadioStation(
        name=name.strip() or _name_from_url(clean_url),
        url=clean_url,
        genre=genre.strip(),
        bitrate=max(0, int(bitrate or 0)),
        tags=tags,
        favorite=bool(favorite),
    )


def station_from_settings(value: object) -> RadioStation | None:
    if not isinstance(value, dict):
        return None
    raw_tags = value.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    tags: tuple[str, ...] = tuple(str(t) for t in raw_tags if t)
    return station_from_url(
        str(value.get("url") or ""),
        name=str(value.get("name") or ""),
        genre=str(value.get("genre") or ""),
        bitrate=_safe_int(value.get("bitrate")),
        tags=tags,
        favorite=bool(value.get("favorite", False)),
    )


def stations_to_m3u(stations: list[RadioStation]) -> str:
    """Serialise a list of stations to an M3U playlist string."""
    lines = ["#EXTM3U"]
    for s in stations:
        lines.append(f"#EXTINF:-1,{s.name}")
        lines.append(s.url)
    return "\n".join(lines)


def stations_to_pls(stations: list[RadioStation]) -> str:
    """Serialise a list of stations to a PLS playlist string."""
    lines = ["[playlist]"]
    for i, s in enumerate(stations, 1):
        lines += [f"File{i}={s.url}", f"Title{i}={s.name}", f"Length{i}=-1"]
    lines += [f"NumberOfEntries={len(stations)}", "Version=2"]
    return "\n".join(lines)


def check_station_health(url: str, *, timeout: float = 5.0) -> tuple[bool, int]:
    """Send HEAD (then GET if HEAD is rejected) to *url* and return ``(ok, status_code)``.

    Returns ``(False, 0)`` on any connection or timeout error.  The GET fallback
    is needed because most Icecast/SHOUTcast servers do not support HEAD.  The
    connection is closed immediately after receiving the response headers so no
    stream data is consumed.
    """
    import urllib.error
    import urllib.request

    ua = radio_user_agent()
    head_error_code = 0
    for method in _HEAD_THEN_GET:
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return True, resp.status
        except urllib.error.HTTPError as exc:
            if method == "HEAD":
                head_error_code = exc.code
                continue  # many stream servers reject HEAD but serve GET
            return exc.code < 400, exc.code
        except Exception:  # noqa: BLE001 — network errors must not crash the caller
            if method == "HEAD":
                head_error_code = 0
                continue
            return False, 0
    return False, head_error_code


def _parse_m3u(text: str, *, base_url: str = "", default_name: str = "") -> list[RadioStation]:
    stations: list[RadioStation] = []
    pending_name = ""
    pending_genre = ""
    pending_bitrate = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("#EXTINF:"):
            pending_name, pending_bitrate = _parse_extinf(line)
            continue
        if upper.startswith("#EXTGRP:"):
            pending_genre = line.split(":", 1)[1].strip()
            continue
        if upper.startswith("#EXT-X-STREAM-INF:"):
            pending_bitrate = _parse_bandwidth_bitrate(line)
            continue
        if line.startswith("#"):
            continue
        url = _resolve_url(line, base_url)
        station = station_from_url(
            url,
            name=pending_name or default_name,
            genre=pending_genre,
            bitrate=pending_bitrate,
        )
        if station is not None:
            stations.append(station)
        pending_name = ""
        pending_genre = ""
        pending_bitrate = 0

    return _dedupe_stations(stations)


def _parse_pls(text: str, *, base_url: str = "") -> list[RadioStation]:
    files: dict[int, str] = {}
    titles: dict[int, str] = {}
    bitrates: dict[int, int] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key_lower = key.strip().casefold()
        value = value.strip()
        if key_lower.startswith("file"):
            files[_safe_int(key_lower[4:])] = value
        elif key_lower.startswith("title"):
            titles[_safe_int(key_lower[5:])] = value
        elif key_lower.startswith("bitrate"):
            bitrates[_safe_int(key_lower[7:])] = _safe_int(value)

    stations: list[RadioStation] = []
    for index in sorted(files):
        url = _resolve_url(files[index], base_url)
        station = station_from_url(
            url,
            name=titles.get(index, ""),
            bitrate=bitrates.get(index, 0),
        )
        if station is not None:
            stations.append(station)
    return _dedupe_stations(stations)


def _parse_extinf(line: str) -> tuple[str, int]:
    payload = line.split(":", 1)[1]
    attrs, name = _split_extinf_payload(payload)
    return name.strip(), _parse_bitrate(attrs)


def _split_extinf_payload(payload: str) -> tuple[str, str]:
    """Split EXTINF attrs from name on the first comma outside quotes."""
    in_quote = False
    for index, ch in enumerate(payload):
        if ch == '"':
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            return payload[:index], payload[index + 1:]
    return payload, ""


def _parse_bitrate(text: str) -> int:
    """Read a bitrate attribute from an EXTINF attribute string.

    The first token is the duration in seconds and must be skipped — otherwise
    `#EXTINF:300,Station` would treat 300s of duration as 300 kbps.
    """
    tokens = text.split(None, 1)
    remainder = tokens[1] if len(tokens) > 1 else ""
    for token in remainder.replace("=", " ").replace('"', " ").split():
        number = _safe_int(token)
        if 0 < number < 10000:
            return number
    return 0


def _parse_bandwidth_bitrate(line: str) -> int:
    marker = "BANDWIDTH="
    upper = line.upper()
    if marker not in upper:
        return 0
    value = line[upper.index(marker) + len(marker):].split(",", 1)[0]
    return _safe_int(value) // 1000


def _resolve_url(value: str, base_url: str) -> str:
    url = _clean_url(value)
    if base_url and not urlparse(url).scheme:
        return urljoin(base_url, url)
    return url


def _clean_url(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _name_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    if parsed.hostname and tail:
        return f"{parsed.hostname} / {tail}"
    return parsed.hostname or url


def _dedupe_stations(stations: list[RadioStation]) -> list[RadioStation]:
    out: list[RadioStation] = []
    seen: set[str] = set()
    for station in stations:
        key = station.url.casefold()
        if key in seen:
            continue
        out.append(station)
        seen.add(key)
    return out


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
