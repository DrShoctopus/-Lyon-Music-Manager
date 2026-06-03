"""Shared YouTube download option metadata and validation helpers."""
from __future__ import annotations

from urllib.parse import urlparse

DEFAULT_YT_BROWSER_COOKIE_BROWSER = "firefox"

# (display label, yt-dlp/settings key) pairs — order matches the Settings combo box.
YT_BROWSER_COOKIE_BROWSERS: tuple[tuple[str, str], ...] = (
    ("Firefox", "firefox"),
    ("Chrome", "chrome"),
    ("Edge", "edge"),
    ("Safari", "safari"),
    ("Chromium", "chromium"),
    ("Brave", "brave"),
    ("Opera", "opera"),
    ("Vivaldi", "vivaldi"),
    ("Whale", "whale"),
)
YT_BROWSER_COOKIE_BROWSER_KEYS = frozenset(key for _label, key in YT_BROWSER_COOKIE_BROWSERS)
_YOUTUBE_COOKIE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
})


def normalize_yt_browser_cookie_browser(value: object) -> str:
    """Return a supported yt-dlp browser-cookie key, or the project default."""
    browser = str(value or DEFAULT_YT_BROWSER_COOKIE_BROWSER).strip().lower()
    if browser in YT_BROWSER_COOKIE_BROWSER_KEYS:
        return browser
    return DEFAULT_YT_BROWSER_COOKIE_BROWSER


def yt_browser_cookies_option(browser_name: object) -> tuple[str] | None:
    """Return the yt-dlp cookies-from-browser tuple for a supported browser."""
    browser = str(browser_name or "").strip().lower()
    if browser in YT_BROWSER_COOKIE_BROWSER_KEYS:
        return (browser,)
    return None


def is_youtube_url(url: object) -> bool:
    """Return True only for YouTube hosts where browser-cookie auth is expected."""
    parsed = urlparse(str(url or "").strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in _YOUTUBE_COOKIE_HOSTS
