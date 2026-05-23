from __future__ import annotations

import threading
import time

import pytest

from lyon.core.cd_detect import DiscToc
from lyon.core.disc_playback import (
    DiscKind,
    cdda_track_options,
    cdda_uri,
    dvd_uri,
    drive_root,
    probe_video_disc,
    tracks_from_audio_cd,
    vcd_uri,
)
from lyon.core.metadata import AlbumInfo, TrackInfo
from lyon.core.settings import Settings

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from lyon.ui.disc_view import DiscView


def _process_events_until(qapp, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def test_disc_mrl_builders_normalize_windows_drive_letters():
    assert cdda_uri("d") == "cdda:///D:/"
    assert cdda_uri("D:") == "cdda:///D:/"
    assert dvd_uri("D:", menus=True) == "dvd:///D:/"
    assert dvd_uri("D:", menus=False) == "dvdsimple:///D:/"
    assert vcd_uri("D:\\") == "vcd:///D:/"
    assert cdda_track_options(3) == (":cdda-track=3",)


def test_drive_root_preserves_full_windows_paths():
    assert drive_root(r"C:\Users\runneradmin\disc") == r"C:\Users\runneradmin\disc"


def test_tracks_from_audio_cd_uses_metadata_and_transient_playback_source():
    toc = DiscToc(
        drive="D:",
        discid="disc-id",
        toc_string="toc",
        track_count=2,
        track_offsets=[0, 7500],
        sectors=15000,
    )
    album = AlbumInfo(
        artist="Artist",
        album="Album",
        date="2026",
        genre="Rock",
        tracks=[
            TrackInfo(1, "First", length_ms=100_000),
            TrackInfo(2, "Second", length_ms=100_000, artist="Guest"),
        ],
    )

    tracks = tracks_from_audio_cd(toc, album)

    assert [track.title for track in tracks] == ["First", "Second"]
    assert tracks[0].duration == 100
    assert tracks[1].artist == "Guest"
    assert all(not track.is_library_item for track in tracks)
    assert all(track.playback_is_location for track in tracks)
    assert tracks[0].playback_uri == "cdda:///D:/"
    assert tracks[1].playback_options == (":cdda-track=2",)


def test_probe_video_disc_detects_dvd_and_vcd_folder_shapes(tmp_path):
    dvd_root = tmp_path / "dvd"
    dvd_root.mkdir()
    (dvd_root / "VIDEO_TS").mkdir()
    source = probe_video_disc(str(dvd_root))
    assert source.kind == DiscKind.DVD
    assert source.uri.startswith("dvd:///")
    assert source.fallback_uri and source.fallback_uri.startswith("dvdsimple:///")

    vcd_root = tmp_path / "vcd"
    vcd_root.mkdir()
    (vcd_root / "MPEGAV").mkdir()
    source = probe_video_disc(str(vcd_root))
    assert source.kind == DiscKind.VCD
    assert source.uri.startswith("vcd:///")


def test_disc_view_populates_audio_cd_tracks(qapp):
    view = DiscView(Settings())
    try:
        toc = DiscToc(
            drive="D:",
            track_count=1,
            track_offsets=[0],
            sectors=7500,
        )
        album = AlbumInfo(
            artist="Artist",
            album="Album",
            tracks=[TrackInfo(1, "Song")],
        )

        view._on_audio_read(toc, album)

        cached_toc, cached_album = view.current_audio_disc()
        assert view.stack.currentWidget() is view.track_table.parentWidget()
        assert cached_toc is toc
        assert cached_album is album
        assert view.track_table.rowCount() == 1
        assert view.track_table.item(0, 1).text() == "Song"
    finally:
        view.shutdown()
        view.deleteLater()


def test_disc_view_eject_clears_cached_audio_disc(qapp, monkeypatch):
    from lyon.core import cd_detect

    view = DiscView(Settings())
    try:
        toc = DiscToc(
            drive="D:",
            track_count=1,
            track_offsets=[0],
            sectors=7500,
        )
        album = AlbumInfo(
            artist="Artist",
            album="Album",
            tracks=[TrackInfo(1, "Song")],
        )
        view._on_audio_read(toc, album)
        view.drive_combo.clear()
        view.drive_combo.addItem("D:")
        view.drive_combo.setCurrentText("D:")
        monkeypatch.setattr(cd_detect, "eject", lambda _drive: None)

        view._eject()

        cached_toc, cached_album = view.current_audio_disc()
        assert cached_toc is None
        assert cached_album is None
        assert view.stack.currentIndex() == 0
    finally:
        view.shutdown()
        view.deleteLater()


def test_disc_view_forced_video_probe_is_asynchronous(qapp, monkeypatch):
    from lyon.ui import disc_view as disc_view_mod

    started = threading.Event()
    release = threading.Event()

    def fake_probe(drive, kind=None):
        started.set()
        release.wait(1.0)
        return probe_video_disc(drive, kind)

    monkeypatch.setattr(disc_view_mod, "probe_video_disc", fake_probe)
    view = DiscView(Settings())
    try:
        view.drive_combo.clear()
        view.drive_combo.addItem("D:")
        view.drive_combo.setCurrentText("D:")
        view.drive_combo.setEnabled(True)
        view.kind_combo.setCurrentText("DVD")

        view.probe_disc()

        assert started.wait(1.0)
        assert view._video_source is None
        assert "Checking video disc" in view.status_label.text()

        release.set()
        assert _process_events_until(qapp, lambda: view._video_source is not None)
        assert view._video_source.kind == DiscKind.DVD
        assert view.stack.currentIndex() == 2
    finally:
        release.set()
        view.shutdown()
        view.deleteLater()


def test_disc_view_play_video_autoplays_after_async_probe(qapp, monkeypatch):
    from lyon.ui import disc_view as disc_view_mod

    release = threading.Event()

    def fake_probe(drive, kind=None):
        release.wait(1.0)
        return probe_video_disc(drive, kind)

    monkeypatch.setattr(disc_view_mod, "probe_video_disc", fake_probe)
    view = DiscView(Settings())
    emitted = []
    view.play_video_disc.connect(lambda source: emitted.append(source))
    try:
        view.drive_combo.clear()
        view.drive_combo.addItem("D:")
        view.drive_combo.setCurrentText("D:")
        view.drive_combo.setEnabled(True)
        view.kind_combo.setCurrentText("DVD")

        view._play_video()

        assert emitted == []
        release.set()
        assert _process_events_until(qapp, lambda: bool(emitted))
        assert emitted[0].kind == DiscKind.DVD
        assert view._video_source is emitted[0]
    finally:
        release.set()
        view.shutdown()
        view.deleteLater()


def test_disc_view_shutdown_terminates_stuck_reader(qapp):
    class StuckReader:
        def __init__(self):
            self.cancelled = False
            self.interruption_requested = False
            self.quit_called = False
            self.terminated = False
            self.waits: list[int] = []

        def cancel(self):
            self.cancelled = True

        def requestInterruption(self):
            self.interruption_requested = True

        def quit(self):
            self.quit_called = True

        def wait(self, timeout):
            self.waits.append(timeout)
            return self.terminated

        def terminate(self):
            self.terminated = True

    view = DiscView(Settings())
    reader = StuckReader()
    view._reader = reader
    try:
        view.shutdown()

        assert reader.cancelled
        assert reader.interruption_requested
        assert reader.quit_called
        assert reader.terminated
        assert reader.waits == [3000, 2000]
        assert view._reader is None
    finally:
        view.deleteLater()


def test_disc_view_shutdown_terminates_stuck_video_probe(qapp):
    class StuckProbe:
        def __init__(self):
            self.cancelled = False
            self.interruption_requested = False
            self.quit_called = False
            self.terminated = False
            self.waits: list[int] = []

        def cancel(self):
            self.cancelled = True

        def requestInterruption(self):
            self.interruption_requested = True

        def quit(self):
            self.quit_called = True

        def wait(self, timeout):
            self.waits.append(timeout)
            return self.terminated

        def terminate(self):
            self.terminated = True

    view = DiscView(Settings())
    probe = StuckProbe()
    view._video_probe = probe
    try:
        view.shutdown()

        assert probe.cancelled
        assert probe.interruption_requested
        assert probe.quit_called
        assert probe.terminated
        assert probe.waits == [3000, 2000]
        assert view._video_probe is None
    finally:
        view.deleteLater()
