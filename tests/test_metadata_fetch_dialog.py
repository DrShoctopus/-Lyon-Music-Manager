from __future__ import annotations

import os
import base64

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.metadata import AlbumInfo
from lyon.core.library import Track
from lyon.ui import metadata_fetch_dialog as metadata_fetch_dialog_module


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACXBIWXMAAA7EAAAOxAGVKw4b"
    "AAAADUlEQVQImWP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def _track() -> Track:
    return Track(
        id=1,
        path="/music/song.flac",
        title="Song",
        artist="Artist",
        album_artist="Artist",
        album="Album",
        track_no=1,
        disc_no=1,
        year=2024,
        genre="",
        duration=180,
    )


class FakeLibrary:
    def __init__(self) -> None:
        self.updated_tracks: list[tuple[int, dict]] = []

    def update_track(self, track_id: int, fields: dict) -> None:
        self.updated_tracks.append((track_id, dict(fields)))


class FakeSignal:
    def __init__(self) -> None:
        self._slots: list[object] = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self) -> None:
        self._slots.clear()

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()


class FakeWorker:
    instances: list["FakeWorker"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.disc_found = FakeSignal()
        self.candidates = FakeSignal()
        self.not_found = FakeSignal()
        self.detail_ready = FakeSignal()
        self.artwork_ready = FakeSignal()
        self.error = FakeSignal()
        self.finished = FakeSignal()
        self.interruption_requested = False
        self.quit_called = False
        self.terminate_called = False
        self.wait_calls: list[int] = []
        self.started = False
        self.delete_later_called = False
        self.parent_set_to_none = False
        self.wait_result = True
        self._running = True
        FakeWorker.instances.append(self)

    def start(self) -> None:
        self.started = True

    def requestInterruption(self) -> None:
        self.interruption_requested = True

    def quit(self) -> None:
        self.quit_called = True

    def isRunning(self) -> bool:
        return self._running

    def wait(self, timeout: int) -> bool:
        self.wait_calls.append(timeout)
        if self.wait_result:
            self._running = False
        return self.wait_result

    def terminate(self) -> None:
        self.terminate_called = True

    def setParent(self, parent) -> None:
        self.parent_set_to_none = parent is None

    def deleteLater(self) -> None:
        self.delete_later_called = True


def test_reject_stops_active_metadata_fetch_workers(qapp, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(metadata_fetch_dialog_module, "_SearchWorker", FakeWorker)

    dialog = metadata_fetch_dialog_module.MetadataFetchDialog(
        [_track()],
        "Artist",
        "Album",
        FakeLibrary(),
    )
    search_worker = dialog._search_worker
    detail_worker = FakeWorker()
    dialog._detail_worker = detail_worker

    dialog.reject()

    assert search_worker.interruption_requested
    assert search_worker.quit_called
    assert search_worker.wait_calls == [100]
    assert not search_worker.terminate_called
    assert search_worker.delete_later_called
    assert dialog._search_worker is None
    assert detail_worker.interruption_requested
    assert detail_worker.quit_called
    assert detail_worker.wait_calls == [100]
    assert not detail_worker.terminate_called
    assert detail_worker.delete_later_called
    assert dialog._detail_worker is None
    dialog.deleteLater()


def test_reject_detaches_metadata_worker_that_does_not_stop_quickly(qapp, monkeypatch):
    FakeWorker.instances.clear()
    metadata_fetch_dialog_module._DETACHED_WORKERS.clear()
    monkeypatch.setattr(metadata_fetch_dialog_module, "_SearchWorker", FakeWorker)

    dialog = metadata_fetch_dialog_module.MetadataFetchDialog(
        [_track()],
        "Artist",
        "Album",
        FakeLibrary(),
    )
    search_worker = dialog._search_worker
    search_worker.wait_result = False

    dialog.reject()

    assert search_worker.interruption_requested
    assert search_worker.quit_called
    assert search_worker.wait_calls == [100]
    assert not search_worker.terminate_called
    assert search_worker.parent_set_to_none
    assert metadata_fetch_dialog_module._DETACHED_WORKERS[id(search_worker)] is search_worker

    search_worker.finished.emit()

    assert id(search_worker) not in metadata_fetch_dialog_module._DETACHED_WORKERS
    assert search_worker.delete_later_called
    dialog.deleteLater()


def test_detail_worker_with_missing_mbid_emits_fallback_album(qapp):
    fallback = AlbumInfo(artist="Artist", album="Album")
    worker = metadata_fetch_dialog_module._DetailWorker(
        "",
        fallback,
        fetch_details=True,
    )
    emitted: list[AlbumInfo] = []
    worker.detail_ready.connect(emitted.append)

    worker.run()

    assert emitted == [fallback]


def test_artwork_arriving_before_diff_is_shown_after_diff(qapp, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(metadata_fetch_dialog_module, "_SearchWorker", FakeWorker)
    dialog = metadata_fetch_dialog_module.MetadataFetchDialog(
        [_track()],
        "Artist",
        "Album",
        FakeLibrary(),
    )

    dialog._on_artwork_ready(PNG_1X1)

    assert dialog._artwork_bytes == PNG_1X1
    assert dialog._artwork_row_w is None

    dialog._show_diff(AlbumInfo(artist="Artist", album="Album"))

    assert dialog._artwork_row_w is not None
    dialog.reject()
    dialog.deleteLater()


def test_apply_handles_unexpected_tag_writer_exception(qapp, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(metadata_fetch_dialog_module, "_SearchWorker", FakeWorker)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        metadata_fetch_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    def fail_write_tags(*_args):
        raise RuntimeError("tag writer exploded")

    monkeypatch.setattr(metadata_fetch_dialog_module, "write_tags", fail_write_tags)
    dialog = metadata_fetch_dialog_module.MetadataFetchDialog(
        [_track()],
        "Artist",
        "Album",
        FakeLibrary(),
    )
    dialog._show_diff(AlbumInfo(artist="Artist", album="Album"))

    dialog._on_apply()

    assert warnings
    assert warnings[0][0] == "Some Metadata Was Not Updated"
    assert "could not be written" in warnings[0][1]
    assert dialog.result() == QtWidgets.QDialog.Accepted
    dialog.deleteLater()
