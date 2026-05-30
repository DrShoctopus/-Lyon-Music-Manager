"""Tests for ``lyon.core.updater`` — appcast parser + version comparator.

The HTTP-fetch worker is exercised with a stub ``Session.get`` so we don't
hit the network in CI.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from lyon.core import updater
from lyon.core.updater import (
    UpdateInfo,
    UpdaterError,
    _is_newer,
    _parse_version,
    check_for_update,
    parse_appcast,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

APPCAST_NEWER = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>Sea Lyon Media Manager</title>
    <item>
      <title>Version 1.0.1</title>
      <pubDate>Mon, 23 May 2026 00:00:00 +0000</pubDate>
      <sparkle:version>1.0.1</sparkle:version>
      <sparkle:minimumSystemVersion>10.0</sparkle:minimumSystemVersion>
      <link>https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/releases/tag/v1.0.1</link>
      <description><![CDATA[<p>Bug fixes and crashes addressed.</p>]]></description>
      <enclosure url="https://example.test/SeaLyonMediaManager-1.0.1-Setup.exe"
                 sparkle:version="1.0.1"
                 length="123456"
                 type="application/octet-stream" />
    </item>
  </channel>
</rss>
"""

APPCAST_SAME = APPCAST_NEWER.replace(">1.0.1<", ">1.0.0<").replace("1.0.1-Setup", "1.0.0-Setup")
APPCAST_OLDER = APPCAST_NEWER.replace(">1.0.1<", ">0.9.0<").replace("1.0.1-Setup", "0.9.0-Setup")
APPCAST_MULTI_OS = APPCAST_NEWER.replace(
    """      <enclosure url="https://example.test/SeaLyonMediaManager-1.0.1-Setup.exe"
                 sparkle:version="1.0.1"
                 length="123456"
                 type="application/octet-stream" />""",
    """      <enclosure url="https://example.test/SeaLyonMediaManager-1.0.1-Setup.exe"
                 sparkle:version="1.0.1"
                 length="123456"
                 type="application/octet-stream"
                 sparkle:os="windows" />
      <enclosure url="https://example.test/SeaLyonMediaManager-1.0.1-arm64.dmg"
                 sparkle:version="1.0.1"
                 length="456789"
                 type="application/octet-stream"
                 sparkle:os="macos" />""",
)

APPCAST_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel><title>Sea Lyon Media Manager</title></channel>
</rss>
"""

APPCAST_MALFORMED = "<not-xml>"


@dataclass
class _StubResponse:
    status_code: int
    text: str


class _StubSession:
    def __init__(self, response: _StubResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[tuple[str, dict, float]] = []

    def get(self, url, *, headers=None, timeout=None, **_kwargs):
        self.calls.append((url, dict(headers or {}), float(timeout or 0)))
        if self._exc is not None:
            raise self._exc
        return self._response


# ---------------------------------------------------------------------------
# Version parsing / comparison
# ---------------------------------------------------------------------------


def test_parse_version_basic():
    assert _parse_version("1.0.0") == _parse_version("v1.0.0")
    assert _parse_version("v1.2.3") > _parse_version("1.2.2")
    assert _parse_version("0.8.0") < _parse_version("1.0.0")


def test_parse_version_orders_prerelease_before_final():
    assert _parse_version("1.0.0-rc1") < _parse_version("1.0.0")
    assert _parse_version("1.0.0+sha") == _parse_version("1.0.0")
    assert _parse_version("1.0.0-rc1+sha") < _parse_version("1.0.0")


def test_parse_version_handles_malformed():
    assert _parse_version("") == _parse_version("0.0.0")
    assert _parse_version("not-a-version") == _parse_version("0.0.0")
    assert _parse_version("1.a.0") == _parse_version("1.0.0")


def test_is_newer():
    assert _is_newer("1.0.1", "1.0.0") is True
    assert _is_newer("2.0.0", "1.99.99") is True
    assert _is_newer("1.0.0", "1.0.0") is False
    assert _is_newer("0.9.0", "1.0.0") is False
    assert _is_newer("1.0.0-rc1", "1.0.0") is False
    assert _is_newer("1.0.0", "1.0.0-rc1") is True
    assert _is_newer("1.0.0-rc2", "1.0.0-rc1") is True


# ---------------------------------------------------------------------------
# parse_appcast
# ---------------------------------------------------------------------------


def test_parse_appcast_newer_release(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")

    info = parse_appcast(APPCAST_NEWER)
    assert isinstance(info, UpdateInfo)
    assert info.version == "1.0.1"
    assert "Bug fixes" in info.release_notes_html
    assert info.download_url == "https://example.test/SeaLyonMediaManager-1.0.1-Setup.exe"
    assert info.release_url == "https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/releases/tag/v1.0.1"
    assert info.minimum_system_version == "10.0"


def test_parse_appcast_selects_macos_enclosure_on_darwin(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "darwin")

    info = parse_appcast(APPCAST_MULTI_OS)

    assert isinstance(info, UpdateInfo)
    assert info.download_url == "https://example.test/SeaLyonMediaManager-1.0.1-arm64.dmg"


def test_parse_appcast_selects_windows_enclosure_on_windows(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")

    info = parse_appcast(APPCAST_MULTI_OS)

    assert isinstance(info, UpdateInfo)
    assert info.download_url == "https://example.test/SeaLyonMediaManager-1.0.1-Setup.exe"


def test_parse_appcast_does_not_offer_windows_installer_on_macos(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "darwin")

    info = parse_appcast(APPCAST_NEWER)

    assert isinstance(info, UpdateInfo)
    assert info.download_url == ""


def test_parse_appcast_empty_channel_returns_none():
    assert parse_appcast(APPCAST_EMPTY) is None


def test_parse_appcast_malformed_raises_updater_error():
    with pytest.raises(UpdaterError):
        parse_appcast(APPCAST_MALFORMED)


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------


def test_check_for_update_returns_info_when_newer():
    session = _StubSession(_StubResponse(200, APPCAST_NEWER))
    info = check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)
    assert info is not None
    assert info.version == "1.0.1"
    # Outbound call must carry our UA + a non-trivial timeout.
    url, headers, timeout = session.calls[0]
    assert "Sea Lyon Media Manager" in headers["User-Agent"]
    assert timeout >= 5.0


def test_check_for_update_returns_none_when_same():
    session = _StubSession(_StubResponse(200, APPCAST_SAME))
    info = check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)
    assert info is None


def test_check_for_update_returns_none_when_older():
    session = _StubSession(_StubResponse(200, APPCAST_OLDER))
    info = check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)
    assert info is None


def test_check_for_update_raises_on_http_error():
    session = _StubSession(_StubResponse(503, "Service Unavailable"))
    with pytest.raises(UpdaterError) as excinfo:
        check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)
    assert "503" in str(excinfo.value)


def test_check_for_update_raises_on_network_error():
    import requests
    session = _StubSession(exc=requests.ConnectionError("nope"))
    with pytest.raises(UpdaterError):
        check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)


def test_check_for_update_rejects_empty_url():
    with pytest.raises(UpdaterError):
        check_for_update("", "1.0.0")


def test_check_for_update_returns_none_when_appcast_empty():
    session = _StubSession(_StubResponse(200, APPCAST_EMPTY))
    info = check_for_update("https://example.test/appcast.xml", "1.0.0", session=session)
    assert info is None


def test_update_check_worker_can_move_to_qthread(qapp):
    QtCore = pytest.importorskip("PySide6.QtCore")
    worker = updater.UpdateCheckWorker("https://example.test/appcast.xml", "1.0.0")
    thread = QtCore.QThread()
    try:
        worker.moveToThread(thread)
        assert worker.parent() is None
        assert worker.thread() is thread
    finally:
        thread.deleteLater()


def test_update_check_worker_uses_close_safe_timeout(qapp, monkeypatch):
    calls: list[float] = []

    def fake_check(appcast_url, current_version, *, timeout, session=None):
        calls.append(float(timeout))
        return None

    monkeypatch.setattr(updater, "check_for_update", fake_check)
    worker = updater.UpdateCheckWorker("https://example.test/appcast.xml", "1.0.0")

    worker.run()

    assert calls
    assert 0 < calls[0] <= 2.5


# ---------------------------------------------------------------------------
# Settings round-trip for the new updater fields
# ---------------------------------------------------------------------------


def test_settings_default_update_check_enabled_true():
    from lyon.core.settings import Settings
    assert Settings().update_check_enabled is True


def test_settings_update_appcast_url_has_https_default():
    from lyon.core.settings import Settings
    url = Settings().update_appcast_url
    assert url.startswith("https://")
    assert "appcast" in url


def test_settings_rejects_non_https_update_appcast_url():
    from lyon.core.settings import Settings

    default_url = Settings().update_appcast_url

    assert Settings(update_appcast_url="http://example.test/appcast.xml").update_appcast_url == default_url
    assert Settings(update_appcast_url="file:///tmp/appcast.xml").update_appcast_url == default_url


def test_skipped_update_version_roundtrips(monkeypatch, tmp_path):
    from lyon.core import settings as settings_mod
    monkeypatch.setattr(settings_mod, "app_data_dir", lambda: tmp_path)
    s = settings_mod.Settings(skipped_update_version="1.0.1")
    s.save()
    loaded = settings_mod.Settings.load()
    assert loaded.skipped_update_version == "1.0.1"


def test_update_dialog_does_not_open_unsafe_download_url(qapp, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from lyon.ui import update_dialog

    opened: list[str] = []
    monkeypatch.setattr(
        update_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    dialog = update_dialog.UpdateAvailableDialog(
        UpdateInfo(
            version="1.0.1",
            title="Version 1.0.1",
            release_notes_html="",
            release_url="",
            download_url="file:///tmp/not-an-installer.exe",
        )
    )

    dialog._on_download()

    assert opened == []


def test_update_dialog_rejects_cleartext_download_url(qapp, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from lyon.ui import update_dialog

    opened: list[str] = []
    monkeypatch.setattr(
        update_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    dialog = update_dialog.UpdateAvailableDialog(
        UpdateInfo(
            version="1.0.1",
            title="Version 1.0.1",
            release_notes_html="",
            release_url="",
            download_url="http://example.test/installer.exe",
        )
    )

    dialog._on_download()

    assert opened == []


def test_update_dialog_filters_release_note_links(qapp, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from lyon.ui import update_dialog
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QTextBrowser

    opened: list[str] = []
    monkeypatch.setattr(
        update_dialog.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    dialog = update_dialog.UpdateAvailableDialog(
        UpdateInfo(
            version="1.0.1",
            title="Version 1.0.1",
            release_notes_html='<a href="file:///tmp/nope">bad</a>',
            release_url="",
            download_url="",
        )
    )
    notes = dialog.findChild(QTextBrowser)
    assert notes is not None
    assert notes.openExternalLinks() is False

    notes.anchorClicked.emit(QUrl("file:///tmp/nope"))
    notes.anchorClicked.emit(QUrl("http://example.test/nope"))
    notes.anchorClicked.emit(QUrl("https://example.test/release"))

    assert opened == ["https://example.test/release"]
