"""Phase 6: dialog typography consistency.

Locks in the contract that user-visible dialog labels use named QSS object
names instead of inline setStyleSheet calls. Catches regressions where
someone reintroduces hard-coded colors / font sizes in dialog code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.player import Player
from lyon.core.settings import Settings

_DIALOG_MODULES = (
    "lyon/ui/settings_dialog.py",
    "lyon/ui/equalizer_dialog.py",
    "lyon/ui/queue_dialog.py",
    "lyon/ui/first_run_dialog.py",
    "lyon/ui/diagnostics_dialog.py",
    "lyon/ui/yt_download_dialog.py",
)


class _FakeBackend(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    position_changed = QtCore.Signal(int, int)
    end_reached = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self._v, self._m, self._p = 80, False, False

    def set_source(self, _, *, is_location=False, options=()): pass
    def play(self): self._p = True
    def pause(self): self._p = False
    def stop(self): self._p = False
    def position(self): return 0
    def duration(self): return 0
    def set_position(self, _): pass
    def set_volume(self, v): self._v = v
    def volume(self): return self._v
    def set_muted(self, m): self._m = m
    def is_muted(self): return self._m
    def is_playing(self): return self._p
    def apply_equalizer(self, *_a, **_k): pass


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.mark.parametrize("module_path", _DIALOG_MODULES)
def test_no_inline_stylesheets_in_dialog_modules(module_path):
    """Inline setStyleSheet drift is the precise bug Phase 6 set out to fix."""
    src = Path(module_path).read_text()
    # Strip comments before scanning so explanatory prose can't false-positive.
    cleaned = re.sub(r"#.*", "", src)
    assert "setStyleSheet" not in cleaned, (
        f"{module_path} still calls setStyleSheet — use a named QSS class instead."
    )


def test_queue_dialog_summary_uses_named_class(app):
    from lyon.ui.queue_dialog import QueueDialog
    player = Player(backend=_FakeBackend())
    dlg = QueueDialog(player)
    assert dlg.summary.objectName() == "dialogSummary"


def test_diagnostics_dialog_summary_uses_named_class(app):
    from lyon.ui.diagnostics_dialog import DiagnosticsDialog
    dlg = DiagnosticsDialog()
    summaries = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "dialogSummary"
    ]
    assert len(summaries) == 1


def test_first_run_dialog_title_and_form_labels_are_named(app):
    from lyon.ui.first_run_dialog import FirstRunDialog
    dlg = FirstRunDialog(Settings.load())
    titles = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "sectionTitle"
    ]
    form_labels = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "formLabel"
    ]
    assert len(titles) >= 1
    assert len(form_labels) == 2  # music root + library folders


def test_settings_about_tab_matches_about_dialog_layout(app):
    """Settings About tab must use the same build_about_widget as Help → About."""
    from lyon import __app_name__, __version__
    from lyon.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings.load())
    labels = [lbl.text() for lbl in dlg.findChildren(QtWidgets.QLabel)]
    # build_about_widget sets a RichText h2 title and a plain version label.
    assert any(__app_name__ in t for t in labels), "App name not found in About tab"
    assert any(__version__ in t for t in labels), "Version not found in About tab"


def test_yt_download_dialog_uses_status_bar_instead_of_log(app, tmp_path):
    from lyon.core.library import Library
    from lyon.ui.widgets import AppProgressBar
    from lyon.ui.yt_download_dialog import YtDownloadDialog

    library = Library(tmp_path / "library.db")
    dlg = YtDownloadDialog(
        "https://www.youtube.com/watch?v=example",
        Settings(music_root=str(tmp_path / "Music")),
        library,
    )

    try:
        assert not dlg.findChildren(QtWidgets.QPlainTextEdit)
        assert isinstance(dlg.status_bar, AppProgressBar)
        assert dlg.status_bar.label() == "Ready"
    finally:
        library.close()
        dlg.deleteLater()


def test_yt_download_dialog_failed_download_marks_status_bar_failed(app, tmp_path):
    from lyon.core.library import Library
    from lyon.ui.yt_download_dialog import YtDownloadDialog

    library = Library(tmp_path / "library.db")
    dlg = YtDownloadDialog(
        "https://www.youtube.com/watch?v=example",
        Settings(music_root=str(tmp_path / "Music")),
        library,
    )

    try:
        dlg._on_download_progress(42, "1:05")
        dlg._on_finished(0, 1)

        assert dlg.status_bar.value() == 100
        assert dlg.status_bar.label() == "Failed"
        assert dlg.status_bar.is_failed()
    finally:
        library.close()
        dlg.deleteLater()


def test_yt_video_success_emits_completion_signal(app, tmp_path):
    from lyon.core.library import Library
    from lyon.ui.yt_download_dialog import YtDownloadDialog

    library = Library(tmp_path / "library.db")
    dlg = YtDownloadDialog(
        "https://www.youtube.com/watch?v=example",
        Settings(music_root=str(tmp_path / "Music")),
        library,
    )
    emitted = []
    dlg.video_download_finished.connect(lambda: emitted.append(True))

    try:
        dlg._active_mode = "audio"
        dlg._on_finished(1, 0)
        dlg._active_mode = "video"
        dlg._on_finished(0, 1)
        dlg._on_finished(1, 0)

        assert emitted == [True]
    finally:
        library.close()
        dlg.deleteLater()


def test_yt_track_ready_refreshes_existing_video_artwork(app, tmp_path):
    from lyon.core.library import Library
    from lyon.ui.yt_download_dialog import YtDownloadDialog

    library = Library(tmp_path / "library.db")
    media_dir = tmp_path / "Music" / "YouTube" / "Uploader"
    media_dir.mkdir(parents=True)
    video = media_dir / "Example Video.mp4"
    video.write_bytes(b"not a real mp4")

    assert library.add_file(video)
    library.commit()
    assert next(library.all_tracks(media_type="video")).artwork_path is None

    thumbnail = media_dir / "Example Video.jpg"
    thumbnail.write_bytes(b"thumbnail")

    dlg = YtDownloadDialog(
        "https://www.youtube.com/watch?v=example",
        Settings(music_root=str(tmp_path / "Music")),
        library,
    )
    emitted = []
    dlg.library_updated.connect(lambda: emitted.append(True))

    try:
        dlg._on_track_ready(str(video))

        track = next(library.all_tracks(media_type="video"))
        assert track.artwork_path == str(thumbnail)
        assert emitted == [True]
    finally:
        library.close()
        dlg.deleteLater()
