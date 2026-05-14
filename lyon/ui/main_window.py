"""Top-level window with WMP-style title, tab bar, stacked views."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractSpinBox, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QStackedWidget, QStatusBar, QTextEdit, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.library import Library
from ..core.player import Player
from ..core.settings import Settings
from .diagnostics_dialog import DiagnosticsDialog
from .equalizer_dialog import EqualizerDialog
from .first_run_dialog import FirstRunDialog
from .library_view import LibraryView
from .now_playing import NowPlayingView, TransportBar
from .queue_dialog import QueueDialog
from .ripper_view import RipperView
from .styles import WMP_QSS
from .video_player_view import VideoPlayerView
from .youtube_view import YouTubeView


class _LibraryScanThread(QThread):
    finished_with = Signal(int, str)  # (new_tracks, label)

    def __init__(self, library: Library, roots: list[str], label: str, parent=None):
        super().__init__(parent)
        self.library = library
        self.roots = roots
        self.label = label
        self._cancel = False

    def request_stop(self) -> None:
        """Ask the scan loop to bail out at the next directory boundary."""
        self._cancel = True

    def run(self) -> None:
        n = self.library.scan_paths(self.roots, should_cancel=lambda: self._cancel)
        self.finished_with.emit(n, self.label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self)
        self.player.set_volume(self.settings.last_volume)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)
        self._scan_thread: _LibraryScanThread | None = None
        self._equalizer_dialog: EqualizerDialog | None = None
        self._queue_dialog: QueueDialog | None = None

        self.setWindowTitle(__app_name__)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(WMP_QSS)

        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- title bar
        title = QFrame()
        title.setObjectName("titlebar")
        tlay = QHBoxLayout(title)
        tlay.setContentsMargins(12, 0, 12, 0)
        tlay.addWidget(QLabel(f"{__app_name__}"))
        tlay.itemAt(0).widget().setObjectName("titleLabel")
        tlay.addStretch(1)
        layout.addWidget(title)

        # ---- tab strip
        tabs = QFrame()
        tabs.setObjectName("tabbar")
        tlayout = QHBoxLayout(tabs)
        tlayout.setContentsMargins(8, 0, 8, 0)
        tlayout.setSpacing(0)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self._tab_buttons: dict[str, QPushButton] = {}
        for name in ("Now Playing", "Library", "Rip", "YouTube", "Video"):
            btn = QPushButton(name)
            btn.setObjectName("navTab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            tlayout.addWidget(btn)
            self.tab_group.addButton(btn)
            self._tab_buttons[name] = btn
        tlayout.addStretch(1)
        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("navTab")
        settings_btn.clicked.connect(self.open_settings)
        tlayout.addWidget(settings_btn)
        queue_btn = QPushButton("Queue")
        queue_btn.setObjectName("navTab")
        queue_btn.clicked.connect(self.open_queue)
        tlayout.addWidget(queue_btn)
        equalizer_btn = QPushButton("10 Band EQ")
        equalizer_btn.setObjectName("navTab")
        equalizer_btn.clicked.connect(self.open_equalizer)
        tlayout.addWidget(equalizer_btn)
        layout.addWidget(tabs)

        # ---- stacked content
        self.stack = QStackedWidget()
        self.now_playing = NowPlayingView(self.player)
        self.library_view = LibraryView(self.library)
        self.ripper_view = RipperView(self.settings, self.library)
        self.youtube_view = YouTubeView()
        self.video_player_view = VideoPlayerView()

        self.stack.addWidget(self.now_playing)
        self.stack.addWidget(self.library_view)
        self.stack.addWidget(self.ripper_view)
        self.stack.addWidget(self.youtube_view)
        self.stack.addWidget(self.video_player_view)

        self._tab_buttons["Now Playing"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.now_playing))
        self._tab_buttons["Library"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.library_view))
        self._tab_buttons["Rip"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.ripper_view))
        self._tab_buttons["YouTube"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.youtube_view))
        self._tab_buttons["Video"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.video_player_view))
        self._tab_buttons["Library"].setChecked(True)

        layout.addWidget(self.stack, 1)

        # ---- transport bar
        self.transport = TransportBar(self.player)
        self.transport.open_now_playing.connect(
            lambda: self._tab_buttons["Now Playing"].setChecked(True))
        self.transport.play_requested.connect(self._on_transport_play_requested)
        layout.addWidget(self.transport)

        self.stack.currentChanged.connect(self._on_view_changed)

        self.setCentralWidget(root)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(f"{__app_name__} {__version__} - ready")

        # Wire library actions
        self.library_view.play_tracks.connect(self.player.set_queue)
        self.library_view.enqueue_tracks.connect(self._enqueue_tracks)
        self.library_view.status_message.connect(lambda m: sb.showMessage(m, 3000))
        self.player.track_changed.connect(self.library_view.highlight_track)
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_rescan.connect(self.rescan)
        self.library_view.request_youtube_search.connect(self._search_youtube_for_track)
        self.ripper_view.rip_completed.connect(self.library_view.refresh)
        self.ripper_view.log.connect(lambda m: sb.showMessage(m, 4000))

        # Initial scan of saved roots. First-run setup owns this scan until the
        # user confirms or skips setup, avoiding duplicate startup scans after
        # upgrading older settings files that do not have first_run_completed.
        if self.settings.library_paths and self.settings.first_run_completed:
            self._start_scan(self.settings.library_paths, "Scanned")

        # Menu
        self._build_menu()
        QTimer.singleShot(0, self._maybe_show_first_run)

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        m = self.menuBar()
        file_menu = m.addMenu("&File")
        file_menu.addAction(QAction("Add Folder to Library...", self,
                                    triggered=self.add_folder))
        file_menu.addAction(QAction("Rescan Library", self, triggered=self.rescan))
        file_menu.addAction(QAction("Remove Missing Files", self,
                                    triggered=self.remove_missing))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Exit", self, triggered=self.close))

        playback_menu = m.addMenu("&Playback")
        play_action = QAction("Play/Pause", self, triggered=self._on_transport_play_requested)
        play_action.setShortcut("Ctrl+Space")
        playback_menu.addAction(play_action)
        prev_action = QAction("Previous", self, triggered=self.player.previous)
        prev_action.setShortcut("Ctrl+Left")
        playback_menu.addAction(prev_action)
        next_action = QAction("Next", self, triggered=self.player.next)
        next_action.setShortcut("Ctrl+Right")
        playback_menu.addAction(next_action)
        queue_action = QAction("Show Queue", self, triggered=self.open_queue)
        queue_action.setShortcut("Ctrl+Q")
        playback_menu.addAction(queue_action)
        search_action = QAction("Focus Library Search", self, triggered=self._focus_library_search)
        search_action.setShortcut("Ctrl+F")
        playback_menu.addAction(search_action)

        help_menu = m.addMenu("&Help")
        help_menu.addAction(QAction("Runtime Diagnostics", self, triggered=self.show_diagnostics))
        help_menu.addAction(QAction("About", self, triggered=self.show_about))

    # ------------------------------------------------------------------ tabs

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Space and not self._focus_widget_accepts_text():
            self._on_transport_play_requested()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _focus_widget_accepts_text(self) -> bool:
        return isinstance(
            self.focusWidget(),
            (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox),
        )

    def _on_transport_play_requested(self) -> None:
        if self.stack.currentWidget() is self.library_view and not self.player.is_playing():
            playback = self.library_view.highlighted_playback()
            if playback is not None:
                tracks, start_index = playback
                self.player.set_queue(tracks, start_index)
                return
        self.player.toggle()

    def _on_view_changed(self, _idx: int) -> None:
        current = self.stack.currentWidget()
        is_youtube = current is self.youtube_view
        is_rip = current is self.ripper_view
        is_video = current is self.video_player_view
        hide_transport = is_youtube or is_rip or is_video
        self.transport.setVisible(not hide_transport)
        if is_youtube or is_rip:
            self.player.stop()
        if not is_youtube:
            self.youtube_view.pause_all_videos()
        if not is_video:
            self.video_player_view.pause_playback()

    # ------------------------------------------------------------------ actions
    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add music folder")
        if not folder:
            return
        if folder not in self.settings.library_paths:
            self.settings.library_paths.append(folder)
            self.settings.save()
        self._start_scan([folder], f"Added tracks from {folder}")

    def rescan(self) -> None:
        self._start_scan(self.settings.library_paths or [self.settings.music_root], "Rescanned")

    def _search_youtube_for_track(self, query: str) -> None:
        if not query:
            return
        self._tab_buttons["YouTube"].setChecked(True)
        if self.youtube_view.search_youtube(query):
            self.statusBar().showMessage(f"Searching YouTube for {query}", 3000)
        else:
            self.statusBar().showMessage("YouTube search is unavailable.", 3000)

    def _enqueue_tracks(self, tracks: list) -> None:
        self.player.enqueue(tracks)
        count = len(tracks)
        total = len(self.player.queue())
        plural = "" if count == 1 else "s"
        queue_plural = "" if total == 1 else "s"
        self.statusBar().showMessage(
            f"Enqueued {count} track{plural}. Queue now has {total} track{queue_plural}.", 3000
        )

    def _start_scan(self, roots: list[str], label: str) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self.statusBar().showMessage("Library scan already running.", 4000)
            return
        self.statusBar().showMessage("Scanning library...")
        self._scan_thread = _LibraryScanThread(self.library, list(roots), label, self)
        self._scan_thread.finished_with.connect(self._on_scan_finished)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_finished(self, n: int, label: str) -> None:
        self.statusBar().showMessage(f"{label}: {n} new tracks", 5000)
        self.library_view.refresh()
        self._scan_thread = None

    def remove_missing(self) -> None:
        n = self.library.remove_missing()
        self.statusBar().showMessage(f"Removed {n} missing tracks", 5000)
        self.library_view.refresh()

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        old_paths = list(self.settings.library_paths)
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings
            self.settings.save()
            self.ripper_view.apply_settings(self.settings)
            self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)
            if self.settings.library_paths != old_paths and self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self.statusBar().showMessage("Settings saved.", 3000)

    def _maybe_show_first_run(self) -> None:
        if self.settings.first_run_completed:
            return
        dlg = FirstRunDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings
            self.settings.save()
            self.ripper_view.apply_settings(self.settings)
            if self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self.statusBar().showMessage("Setup saved.", 3000)

    def show_diagnostics(self) -> None:
        DiagnosticsDialog(parent=self).exec()

    def open_queue(self) -> None:
        if self._queue_dialog is None:
            self._queue_dialog = QueueDialog(self.player, self)
            self._queue_dialog.finished.connect(self._clear_queue_dialog)
        self._queue_dialog.show()
        self._queue_dialog.raise_()
        self._queue_dialog.activateWindow()

    def _clear_queue_dialog(self, *_args) -> None:
        self._queue_dialog = None

    def _focus_library_search(self) -> None:
        self._tab_buttons["Library"].setChecked(True)
        self.library_view.search.setFocus()
        self.library_view.search.selectAll()

    def open_equalizer(self) -> None:
        if self._equalizer_dialog is None:
            self._equalizer_dialog = EqualizerDialog(self.settings, self)
            self._equalizer_dialog.equalizer_changed.connect(self.player.set_equalizer)
            self._equalizer_dialog.settings_saved.connect(self._apply_equalizer_settings)
            self._equalizer_dialog.finished.connect(self._clear_equalizer_dialog)
        self._equalizer_dialog.show()
        self._equalizer_dialog.raise_()
        self._equalizer_dialog.activateWindow()

    def _apply_equalizer_settings(self, settings: Settings) -> None:
        self.settings.equalizer_enabled = settings.equalizer_enabled
        self.settings.equalizer_bands = list(settings.equalizer_bands)
        self.settings.equalizer_curve_name = settings.equalizer_curve_name
        self.settings.equalizer_custom_curves = dict(settings.equalizer_custom_curves)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)
        self.statusBar().showMessage("Equalizer settings saved.", 3000)

    def _clear_equalizer_dialog(self, *_args) -> None:
        self._equalizer_dialog = None

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__} {__version__}</h3>"
            "<p><b>Custom Built For Chuck Lyon</b></p>"
            "<p>Rip your CDs to FLAC, manage your library, browse YouTube, "
            "and play music with a familiar Windows Media Player look.</p>"
            "<p>Uses MusicBrainz, Cover Art Archive, ffmpeg, and Qt WebEngine.</p>",
        )

    def closeEvent(self, ev) -> None:
        # Stop audio first so it doesn't bleed past the visible window.
        self.player.stop()
        # Tell the library scan to bail at the next directory boundary, then
        # block until it actually exits. quit() alone is a no-op because the
        # scan thread overrides run() and never enters an event loop.
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.request_stop()
            self._scan_thread.wait()
        # Cancel any in-flight rip / disc lookup so worker threads don't
        # outlive the window.
        self.ripper_view.shutdown()
        self.settings.last_volume = self.player.volume()
        self.settings.save()
        super().closeEvent(ev)
