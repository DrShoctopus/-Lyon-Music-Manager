"""Sparkle-style appcast XML poller for the in-app update notifier.

The release pipeline publishes an ``appcast.xml`` to GitHub Pages on every
release. The app polls that URL at most once every 24 hours (with the
"Check for updates automatically" setting enabled) and surfaces a non-modal
dialog when a newer version is available.

We deliberately do **not** download or apply updates in-place; the
"Download Now" button in :class:`lyon.ui.update_dialog.UpdateAvailableDialog`
opens the enclosure URL in the user's default browser. In-place patching is
post-1.0.

Appcast format (Sparkle 2.0; signatures omitted for the v1.0 unsigned ship):

.. code-block:: xml

    <rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
      <channel>
        <title>Sea Lyon Media Manager</title>
        <item>
          <title>Version 1.0.1</title>
          <pubDate>Mon, 23 May 2026 00:00:00 +0000</pubDate>
          <sparkle:version>1.0.1</sparkle:version>
          <sparkle:minimumSystemVersion>10.0</sparkle:minimumSystemVersion>
          <link>https://github.com/.../releases/tag/v1.0.1</link>
          <description><![CDATA[<p>What's new...</p>]]></description>
          <enclosure
              url="https://.../SeaLyonMediaManager-1.0.1-Setup.exe"
              sparkle:version="1.0.1"
              length="...bytes..."
              type="application/octet-stream" />
        </item>
      </channel>
    </rss>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import defusedxml.ElementTree as ET
import requests
from defusedxml.common import DefusedXmlException
from PySide6.QtCore import QObject, Signal

LOG = logging.getLogger(__name__)

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"

_REQUEST_TIMEOUT_SECONDS = 10.0
_XML_EXCEPTIONS = (ET.ParseError, DefusedXmlException)


def _updater_user_agent() -> str:
    """Identify the app in outbound appcast requests."""
    from .. import __version__
    from .settings import DEFAULT_MUSICBRAINZ_CONTACT, get_cached_settings

    contact = ""
    try:
        contact = (get_cached_settings().musicbrainz_contact or "").strip()
    except Exception:  # noqa: BLE001
        contact = ""
    if not contact:
        contact = DEFAULT_MUSICBRAINZ_CONTACT
    return f"Sea Lyon Media Manager/{__version__} (+{contact}) Updater/1.0"


@dataclass(frozen=True)
class UpdateInfo:
    """Metadata for a single appcast ``<item>``."""

    version: str               # e.g. "1.0.1"
    title: str                 # "Version 1.0.1"
    release_notes_html: str    # CDATA content of <description>
    release_url: str           # <link> — release tag page
    download_url: str          # <enclosure url=...> — the installer URL
    minimum_system_version: str = ""  # sparkle:minimumSystemVersion if present


class UpdaterError(Exception):
    """Raised when the appcast cannot be fetched or parsed."""


def _parse_version(value: str) -> tuple[int, ...]:
    """Return a comparable tuple of ints from a dotted version string.

    Falls back to ``(0,)`` on malformed input rather than raising, so a
    typo in the appcast can't break the startup check. Pre-release suffixes
    (e.g. ``1.0.0-rc1``) are stripped to the numeric prefix.
    """
    if not value:
        return (0,)
    head = value.strip().lstrip("vV")
    # Strip pre-release / build metadata: "1.0.0-rc1+sha" -> "1.0.0".
    for sep in ("-", "+"):
        if sep in head:
            head = head.split(sep, 1)[0]
    parts: list[int] = []
    for component in head.split("."):
        try:
            parts.append(int(component))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def _is_newer(candidate: str, current: str) -> bool:
    return _parse_version(candidate) > _parse_version(current)


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _first_item(root: ET.Element) -> ET.Element | None:
    """Return the first ``<item>`` under any ``<channel>``."""
    channel = root.find("channel")
    if channel is None:
        return None
    return channel.find("item")


def parse_appcast(text: str) -> UpdateInfo | None:
    """Parse the most recent ``<item>`` block out of an appcast XML.

    Returns ``None`` if the document is well-formed but contains no items.
    Raises :class:`UpdaterError` on malformed XML or missing required fields.
    """
    try:
        root = ET.fromstring(text)
    except _XML_EXCEPTIONS as exc:
        raise UpdaterError(f"Invalid appcast XML: {exc}") from exc
    item = _first_item(root)
    if item is None:
        return None

    version = _text(item.find(f"{{{SPARKLE_NS}}}version"))
    if not version:
        # Sparkle 1.x sometimes puts the version on <enclosure>.
        enclosure = item.find("enclosure")
        if enclosure is not None:
            version = (enclosure.attrib.get(f"{{{SPARKLE_NS}}}version") or "").strip()
    if not version:
        raise UpdaterError("Appcast item has no sparkle:version.")

    enclosure = item.find("enclosure")
    download_url = (enclosure.attrib.get("url") if enclosure is not None else "") or ""

    release_url = _text(item.find("link"))
    title = _text(item.find("title")) or f"Version {version}"
    description = _text(item.find("description"))
    minimum = _text(item.find(f"{{{SPARKLE_NS}}}minimumSystemVersion"))

    return UpdateInfo(
        version=version,
        title=title,
        release_notes_html=description,
        release_url=release_url,
        download_url=download_url.strip(),
        minimum_system_version=minimum,
    )


def check_for_update(
    appcast_url: str,
    current_version: str,
    *,
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> UpdateInfo | None:
    """Fetch the appcast and return an :class:`UpdateInfo` if newer, else ``None``.

    Network failures, HTTP errors, and malformed XML are translated into
    :class:`UpdaterError` so the caller can render a single "couldn't check"
    surface. A well-formed appcast that's older or equal returns ``None``.
    """
    if not appcast_url:
        raise UpdaterError("No appcast URL configured.")
    headers = {"User-Agent": _updater_user_agent(), "Accept": "application/rss+xml, application/xml"}
    fetch = session.get if session is not None else requests.get
    try:
        response = fetch(appcast_url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UpdaterError(f"Could not reach update server: {exc}") from exc
    if response.status_code != 200:
        raise UpdaterError(
            f"Update server returned HTTP {response.status_code}."
        )
    info = parse_appcast(response.text)
    if info is None:
        return None
    if _is_newer(info.version, current_version):
        return info
    return None


# ---------------------------------------------------------------------------
# Qt worker — runs the network call off the UI thread.
# ---------------------------------------------------------------------------


class UpdateCheckWorker(QObject):
    """Background worker that fetches the appcast and emits the result.

    Move this parentless object to a ``QThread`` before calling ``run()``.
    The worker emits exactly one of ``finished`` (with the parsed
    :class:`UpdateInfo` or ``None``) or ``failed`` (with a short message).
    Connect ``finished`` and ``failed`` to slots before starting the thread.
    """

    finished = Signal(object)   # UpdateInfo | None
    failed = Signal(str)

    def __init__(
        self,
        appcast_url: str,
        current_version: str,
    ) -> None:
        super().__init__(None)
        self._appcast_url = appcast_url
        self._current_version = current_version

    def run(self) -> None:
        try:
            info = check_for_update(self._appcast_url, self._current_version)
        except UpdaterError as exc:
            LOG.debug("Update check failed: %s", exc)
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — never crash the worker
            LOG.exception("Unexpected error during update check")
            self.failed.emit(str(exc))
            return
        self.finished.emit(info)
