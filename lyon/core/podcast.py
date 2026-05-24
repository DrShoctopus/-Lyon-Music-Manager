"""Podcast feed parsing and subscription helpers."""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

_XML_EXCEPTIONS = (ET.ParseError, DefusedXmlException)


_ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_MEDIA_NS = "http://search.yahoo.com/mrss/"
_AUDIO_MIME_PREFIXES = ("audio/", "video/")
_ENCLOSURE_REL_VALUES = {"enclosure", "http://www.iana.org/assignments/relation/enclosure"}
MAX_FEED_SIZE = 10 * 1024 * 1024


def podcast_user_agent() -> str:
    """Return a Sea Lyon UA string with version + contact for outbound feed fetches."""
    from .settings import get_cached_settings
    from .user_agent import component_user_agent

    try:
        settings = get_cached_settings()
    except Exception:  # noqa: BLE001 — UA must never crash a podcast fetch
        from .settings import Settings
        settings = Settings()
    return component_user_agent("Podcast", settings)


@dataclass(frozen=True)
class PodcastSubscription:
    title: str
    url: str
    homepage: str = ""
    description: str = ""
    artwork_url: str = ""

    def as_settings_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "homepage": self.homepage,
            "description": self.description,
            "artwork_url": self.artwork_url,
        }


@dataclass(frozen=True)
class PodcastEpisode:
    feed_title: str
    title: str
    url: str
    feed_url: str = ""
    guid: str = ""
    published: str = ""
    description: str = ""
    duration: str = ""
    web_url: str = ""
    artwork_url: str = ""


@dataclass(frozen=True)
class PodcastFeed:
    title: str
    url: str = ""
    homepage: str = ""
    description: str = ""
    artwork_url: str = ""
    episodes: tuple[PodcastEpisode, ...] = ()

    def subscription(self) -> PodcastSubscription:
        return PodcastSubscription(
            title=self.title or self.url,
            url=self.url,
            homepage=self.homepage,
            description=self.description,
            artwork_url=self.artwork_url,
        )


def fetch_feed(url: str, *, timeout: int = 15) -> PodcastFeed:
    """Download and parse a podcast feed URL."""
    clean_url = _clean_url(url)
    if not _is_http_url(clean_url):
        raise ValueError("Podcast feed URL must be HTTP or HTTPS.")
    request = Request(clean_url, headers={"User-Agent": podcast_user_agent()})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-supplied podcast URLs are expected.
        data = response.read(MAX_FEED_SIZE + 1)
    if len(data) > MAX_FEED_SIZE:
        raise ValueError("Podcast feed is too large.")
    text = data.decode("utf-8-sig", errors="replace")
    return parse_feed_text(text, source_url=clean_url)


def parse_feed_file(path: str | Path) -> PodcastFeed:
    feed_path = Path(path)
    return parse_feed_text(
        feed_path.read_text(encoding="utf-8-sig", errors="replace"),
        source_url=feed_path.as_uri(),
    )


def parse_feed_text(text: str, *, source_url: str = "") -> PodcastFeed:
    """Parse an RSS or Atom podcast feed into normalized episode entries."""
    root = _parse_xml(text, "podcast feed")
    tag = _local_name(root.tag).casefold()
    if tag == "rss" or root.find("channel") is not None:
        return _parse_rss(root, source_url=source_url)
    if tag == "feed":
        return _parse_atom(root, source_url=source_url)
    raise ValueError("Unsupported podcast feed format.")


def parse_opml_text(text: str, *, base_url: str = "") -> list[PodcastSubscription]:
    """Extract podcast feed subscriptions from OPML outline XML."""
    root = _parse_xml(text, "OPML")
    subscriptions: list[PodcastSubscription] = []
    seen: set[str] = set()
    for outline in root.iter():
        if _local_name(outline.tag).casefold() != "outline":
            continue
        url = _clean_url(outline.attrib.get("xmlUrl") or outline.attrib.get("xmlurl") or "")
        if not url:
            continue
        url = urljoin(base_url, url)
        if not _is_http_url(url):
            continue
        key = url.casefold()
        if key in seen:
            continue
        title = (
            outline.attrib.get("title")
            or outline.attrib.get("text")
            or _title_from_url(url)
        )
        subscriptions.append(PodcastSubscription(str(title).strip(), url))
        seen.add(key)
    return subscriptions


def parse_opml_file(path: str | Path) -> list[PodcastSubscription]:
    opml_path = Path(path)
    return parse_opml_text(
        opml_path.read_text(encoding="utf-8-sig", errors="replace"),
        base_url=opml_path.as_uri(),
    )


def subscription_from_settings(value: object) -> PodcastSubscription | None:
    if not isinstance(value, dict):
        return None
    url = _clean_url(str(value.get("url") or ""))
    if not _is_http_url(url):
        return None
    title = str(value.get("title") or "").strip() or url
    return PodcastSubscription(
        title=title,
        url=url,
        homepage=str(value.get("homepage") or "").strip(),
        description=str(value.get("description") or "").strip(),
        artwork_url=_clean_url(str(value.get("artwork_url") or "")),
    )


def _parse_rss(root: ET.Element, *, source_url: str) -> PodcastFeed:
    channel = root.find("channel")
    if channel is None:
        channel = root
    title = _child_text(channel, "title") or _title_from_url(source_url)
    homepage = _resolve_url(_child_text(channel, "link"), source_url)
    description = _child_text(channel, "description")
    artwork_url = _rss_artwork_url(channel, source_url)
    episodes: list[PodcastEpisode] = []
    for item in channel.findall("item"):
        episode_url = _rss_episode_url(item, source_url)
        if not episode_url:
            continue
        episode_title = _child_text(item, "title") or _title_from_url(episode_url)
        episodes.append(PodcastEpisode(
            feed_title=title,
            title=episode_title,
            url=episode_url,
            feed_url=source_url,
            guid=_child_text(item, "guid"),
            published=_format_date(_child_text(item, "pubDate") or _child_text(item, "published")),
            description=_child_text(item, "description"),
            duration=_normalize_duration(_namespaced_child_text(item, _ITUNES_NS, "duration")),
            web_url=_resolve_url(_child_text(item, "link"), source_url),
            artwork_url=_rss_artwork_url(item, source_url) or artwork_url,
        ))
    return PodcastFeed(
        title=title,
        url=source_url,
        homepage=homepage,
        description=description,
        artwork_url=artwork_url,
        episodes=tuple(episodes),
    )


def _parse_atom(root: ET.Element, *, source_url: str) -> PodcastFeed:
    title = _child_text(root, "title") or _title_from_url(source_url)
    homepage = _atom_link(root, source_url, rel_values={"alternate", ""})
    description = _child_text(root, "subtitle") or _child_text(root, "summary")
    artwork_url = _resolve_url(_child_text(root, "icon") or _child_text(root, "logo"), source_url)
    episodes: list[PodcastEpisode] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry") + root.findall("entry"):
        episode_url = _atom_link(entry, source_url, rel_values=_ENCLOSURE_REL_VALUES)
        if not episode_url:
            continue
        episode_title = _child_text(entry, "title") or _title_from_url(episode_url)
        episodes.append(PodcastEpisode(
            feed_title=title,
            title=episode_title,
            url=episode_url,
            feed_url=source_url,
            guid=_child_text(entry, "id"),
            published=_format_date(_child_text(entry, "published") or _child_text(entry, "updated")),
            description=_child_text(entry, "summary") or _child_text(entry, "content"),
            duration=_normalize_duration(_namespaced_child_text(entry, _ITUNES_NS, "duration")),
            web_url=_atom_link(entry, source_url, rel_values={"alternate", ""}),
            artwork_url=artwork_url,
        ))
    return PodcastFeed(
        title=title,
        url=source_url,
        homepage=homepage,
        description=description,
        artwork_url=artwork_url,
        episodes=tuple(episodes),
    )


def _rss_episode_url(item: ET.Element, source_url: str) -> str:
    for enclosure in item.findall("enclosure"):
        url = _clean_url(enclosure.attrib.get("url") or "")
        mime_type = str(enclosure.attrib.get("type") or "").casefold()
        if url and (not mime_type or mime_type.startswith(_AUDIO_MIME_PREFIXES)):
            return _resolve_url(url, source_url)
    for media in item.findall(f"{{{_MEDIA_NS}}}content"):
        url = _clean_url(media.attrib.get("url") or "")
        medium = str(media.attrib.get("medium") or "").casefold()
        mime_type = str(media.attrib.get("type") or "").casefold()
        if url and (medium in {"audio", "video"} or mime_type.startswith(_AUDIO_MIME_PREFIXES)):
            return _resolve_url(url, source_url)
    return ""


def _rss_artwork_url(parent: ET.Element, source_url: str) -> str:
    image = parent.find("image")
    if image is not None:
        image_url = _child_text(image, "url")
        if image_url:
            return _resolve_url(image_url, source_url)
    itunes_image = parent.find(f"{{{_ITUNES_NS}}}image")
    if itunes_image is not None:
        href = _clean_url(itunes_image.attrib.get("href") or "")
        if href:
            return _resolve_url(href, source_url)
    return ""


def _atom_link(parent: ET.Element, source_url: str, *, rel_values: set[str]) -> str:
    for link in parent.findall(f"{{{_ATOM_NS}}}link") + parent.findall("link"):
        rel = str(link.attrib.get("rel") or "").strip().casefold()
        if rel not in rel_values:
            continue
        href = _clean_url(link.attrib.get("href") or "")
        if href:
            return _resolve_url(href, source_url)
    return ""


def _child_text(parent: ET.Element, local_name: str) -> str:
    for child in list(parent):
        if _local_name(child.tag).casefold() == local_name.casefold():
            return "".join(child.itertext()).strip()
    return ""


def _namespaced_child_text(parent: ET.Element, namespace: str, local_name: str) -> str:
    child = parent.find(f"{{{namespace}}}{local_name}")
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_xml(text: str, label: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except _XML_EXCEPTIONS as exc:
        raise ValueError(f"Invalid {label} XML.") from exc


def _resolve_url(value: str, base_url: str) -> str:
    url = _clean_url(value)
    if base_url and url:
        return _quote_url(urljoin(base_url, url))
    return _quote_url(url)


def _clean_url(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _quote_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        quote(parsed.path, safe="/:%@!$&'()*+,;=-._~%"),
        parsed.params,
        quote(parsed.query, safe="=&?/:@!$'()*+,;%-._~"),
        quote(parsed.fragment, safe="=&?/:@!$'()*+,;%-._~"),
    ))


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).stem or Path(parsed.path).name
    return tail or parsed.hostname or url


def _format_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, IndexError, AttributeError):
        return text[:10] if len(text) >= 10 else text


def _normalize_duration(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if ":" in text:
        parts = [part.zfill(2) for part in text.split(":")]
        return ":".join(parts)
    try:
        seconds = max(0, int(float(text)))
    except (TypeError, ValueError):
        return text
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
