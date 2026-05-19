from __future__ import annotations

import pytest

from lyon.core.cd_detect import DiscToc
from lyon.core.disc_playback import (
    DiscKind,
    cdda_track_options,
    cdda_uri,
    dvd_uri,
    probe_video_disc,
    tracks_from_audio_cd,
    vcd_uri,
)
from lyon.core.metadata import AlbumInfo, TrackInfo
from lyon.core.settings import Settings

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from lyon.ui.disc_view import DiscView


def test_disc_mrl_builders_normalize_windows_drive_letters():
    assert cdda_uri("d") == "cdda:///D:/"
    assert cdda_uri("D:") == "cdda:///D:/"
    assert dvd_uri("D:", menus=True) == "dvd:///D:/"
    assert dvd_uri("D:", menus=False) == "dvdsimple:///D:/"
    assert vcd_uri("D:\\") == "vcd:///D:/"
    assert cdda_track_options(3) == (":cdda-track=3",)


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

        assert view.stack.currentWidget() is view.track_table.parentWidget()
        assert view.track_table.rowCount() == 1
        assert view.track_table.item(0, 1).text() == "Song"
    finally:
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
