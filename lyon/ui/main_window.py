"""Top-level window with native tab bar and stacked views."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QStackedWidget, QStatusBar, QTabBar, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core import metadata
from ..core.cd_detect import close_dll_handles as close_cd_dll_handles
from ..core.library import Library
from ..core.playback_backend import close_dll_handles
from ..core.player import Player
from ..core.settings import Settings
from .branding import app_icon
from .diagnostics_dialog import DiagnosticsDialog
from .equalizer_dialog import EqualizerDialog
from .first_run_dialog import FirstRunDialog
from .library_view import LibraryView
from .now_playing import NowPlayingView, TransportBar
from .queue_dialog import QueueDialog
from .ripper_view import RipperView
from .styles import WMP_QSS
from .toast import Toast
from .video_player_view import VideoPlayerView
from .yt_download_dialog import YtDownloadDialog
from .youtube_view import YouTubeView


class _LibraryScanThread(QThread):
    finished_with = Signal(int, int, str)  # (new_tracks, removed_tracks, label)

    def __init__(self, library: Library, roots: list[str], label: str, prune: bool = False, parent=None):
        super().__init__(parent)
        self.library = library
        self.roots = roots
        self.label = label
        self.prune = prune
        self._cancel = False

    def request_stop(self) -> None:
        """Ask the scan loop to bail out at the next directory boundary."""
        self._cancel = True

    def run(self) -> None:
        removed = self.library.remove_missing() if self.prune else 0
        n = self.library.scan_paths(self.roots, should_cancel=lambda: self._cancel)
        self.finished_with.emit(n, removed, self.label)


class MainWindow(QMainWindow):
    # Tab display order — index matches the QStackedWidget page index.
    _TAB_ORDER = ("Library", "Now Playing", "Video", "Rip", "YouTube")

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self)
        self.player.set_volume(self.settings.last_volume)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self._scan_thread: _LibraryScanThread | None = None
        self._equalizer_dialog: EqualizerDialog | None = None
        self._queue_dialog: QueueDialog | None = None
        self._current_toast: Toast | None = None
        # Debounce rapid library_updated signals (e.g. playlist downloads).
        self._library_refresh_timer = QTimer(self)
        self._library_refresh_timer.setSingleShot(True)
        self._library_refresh_timer.setInterval(300)

        self.setWindowTitle(__app_name__)
        self.setWindowIcon(app_icon())
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(WMP_QSS)

        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header bar: tab bar + tool buttons
        header = QWidget()
        header.setObjectName("headerBar")
        hlayout = QHBoxLayout(header)
        hlayout.setContentsMargins(8, 0, 8, 0)
        hlayout.setSpacing(0)

        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setCursor(Qt.PointingHandCursor)
        hlayout.addWidget(self.tab_bar)
        hlayout.addStretch(1)

        for label, tooltip, handler in (
            ("Queue",    "Show playback queue  [Ctrl+Q]", self.open_queue),
            ("EQ",       "Open 10-band equalizer",        self.open_equalizer),
            ("Settings", "Open Settings",                 self.open_settings),
        ):
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tooltip)
            btn.setObjectName("navToolBtn")
            btn.clicked.connect(handler)
            hlayout.addWidget(btn)

        layout.addWidget(header)

        # ---- stacked content (order must match _TAB_ORDER)
        self.stack = QStackedWidget()
        self.library_view = LibraryView(self.library)
        self._library_refresh_timer.timeout.connect(self.library_view.refresh)
        self.now_playing = NowPlayingView(self.player)
        self.video_player_view = VideoPlayerView(
            library=self.library,
            initial_volume=self.settings.last_volume,
        )
        self.video_player_view.apply_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self._library_refresh_timer.timeout.connect(self.video_player_view.refresh_catalog)
        self.ripper_view = RipperView(self.settings, self.library)
        self.youtube_view = YouTubeView()

        # Build tab bar + stack together so indices always match _TAB_ORDER.
        _tab_views = (
            self.library_view,
            self.now_playing,
            self.video_player_view,
            self.ripper_view,
            self.youtube_view,
        )
        self._tab_index: dict[str, int] = {}
        for idx, (name, view) in enumerate(zip(self._TAB_ORDER, _tab_views)):
            self.tab_bar.addTab(name)
            self.stack.addWidget(view)
            self._tab_index[name] = idx

        self.tab_bar.currentChanged.connect(self.stack.setCurrentIndex)
        self.stack.currentChanged.connect(self._on_view_changed)
        layout.addWidget(self.stack, 1)

        # ---- transport bar
        self.transport = TransportBar(self.player)
        self.transport.open_now_playing.connect(
            lambda: self.tab_bar.setCurrentIndex(self._tab_index["Now Playing"]))
        self.transport.play_requested.connect(self._on_transport_play_requested)
        layout.addWidget(self.transport)

        self.setCentralWidget(root)

        # Status bar with permanent scan-progress indicator
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._scan_status_label = QLabel("")
        self._scan_status_label.setObjectName("mutedTextSmall")
        self._scan_status_label.setVisible(False)
        self._scan_progress = QProgressBar()
        self._scan_progress.setRange(0, 0)  # indeterminate (busy spinner)
        self._scan_progress.setMaximumWidth(120)
        self._scan_progress.setMaximumHeight(14)
        self._scan_progress.setTextVisible(False)
        self._scan_progress.setVisible(False)
        sb.addPermanentWidget(self._scan_status_label)
        sb.addPermanentWidget(self._scan_progress)
        sb.showMessage(f"{__app_name__} {__version__} - ready")

        # Wire library actions
        self.library_view.play_tracks.connect(self.player.set_queue)
        self.library_view.enqueue_tracks.connect(self._enqueue_tracks)
        self.library_view.status_message.connect(
            lambda m: self.show_toast(m, level="warning"))
        self.player.track_changed.connect(self.library_view.highlight_track)
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_rescan.connect(self.rescan)
        self.library_view.request_youtube_search.connect(self._search_youtube_for_track)
        self.library_view.request_open_settings.connect(self.open_settings)
        self.library_view.request_diagnostics.connect(self.show_diagnostics)
        self.video_player_view.request_diagnostics.connect(self.show_diagnostics)
        self.ripper_view.rip_completed.connect(self.library_view.refresh)
        self.ripper_view.log.connect(lambda m: sb.showMessage(m, 4000))
        self.youtube_view.download_requested.connect(self._on_yt_download)

        self.setAcceptDrops(True)

        # Initial scan of saved roots.
        if self.settings.library_paths and self.settings.first_run_completed:
            self._start_scan(self.settings.library_paths, "Scanned")

        # Menu + keyboard shortcuts
        self._build_menu()

        # Ensure transport visibility matches initial tab (Library, index 0).
        self._on_view_changed(0)

        QTimer.singleShot(0, self._maybe_show_first_run)
        backup_path = getattr(self.settings, "_corrupt_backup_path", None)
        if backup_path:
            QTimer.singleShot(
                200,
                lambda: QMessageBox.warning(
                    self,
                    "Settings Reset",
                    "Your settings file was corrupted and has been reset to defaults.\n"
                    f"The bad file was saved to:\n{backup_path}",
                ),
            )

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
        exit_act = QAction("Exit", self, triggered=self.close)
        exit_act.setMenuRole(QAction.MenuRole.QuitRole)
        file_menu.addAction(exit_act)

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

        # View menu with Ctrl+1..5 tab shortcuts
        view_menu = m.addMenu("&View")
        for idx, name in enumerate(self._TAB_ORDER):
            act = QAction(name, self)
            act.setShortcut(f"Ctrl+{idx + 1}")
            act.triggered.connect(
                lambda checked=False, i=idx: self.tab_bar.setCurrentIndex(i)
            )
            view_menu.addAction(act)

        settings_menu = m.addMenu("&Settings")
        settings_act = QAction("Open Settings", self, triggered=self.open_settings)
        settings_act.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        settings_menu.addAction(settings_act)

        help_menu = m.addMenu("&Help")
        help_menu.addAction(QAction("Runtime Diagnostics", self, triggered=self.show_diagnostics))
        about_act = QAction("About", self, triggered=self.show_about)
        about_act.setMenuRole(QAction.MenuRole.AboutRole)
        help_menu.addAction(about_act)

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

    # ------------------------------------------------------------------ toasts
    def show_toast(
        self,
        message: str,
        level: str = "info",
        duration_ms: int = 2500,
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> Toast:
        """Display a transient toast notification above the transport bar.

        `action` is an optional (label, callback) pair that adds an inline
        button to the toast; clicking it fires the callback and dismisses.
        """
        if self._current_toast is not None:
            self._current_toast.dismiss()
            self._current_toast = None

        action_label = action[0] if action else None
        toast = Toast(
            message,
            level=level,
            duration_ms=duration_ms,
            action_label=action_label,
            parent=self,
        )
        if action and toast.action_button is not None:
            cb = action[1]

            def _run_action() -> None:
                try:
                    cb()
                finally:
                    toast.dismiss()

            toast.action_button.clicked.connect(_run_action)
        toast.closed.connect(lambda: self._on_toast_closed(toast))
        self._current_toast = toast
        toast.show_at(self, bottom_margin=self._toast_bottom_margin())
        return toast

    def _on_toast_closed(self, toast: Toast) -> None:
        if self._current_toast is toast:
            self._current_toast = None

    def _toast_bottom_margin(self) -> int:
        # Float the toast above the transport bar when it's visible.
        base = 24
        if getattr(self, "transport", None) is not None and self.transport.isVisible():
            base += self.transport.sizeHint().height()
        return base

    def resizeEvent(self, ev) -> None:  # noqa: N802 (Qt signature)
        super().resizeEvent(ev)
        if self._current_toast is not None:
            self._current_toast.reposition(self._toast_bottom_margin())

    def _on_view_changed(self, _idx: int) -> None:
        current = self.stack.currentWidget()
        is_rip = current is self.ripper_view
        is_video = current is self.video_player_view
        self.transport.setVisible(not is_rip and not is_video)
        if is_rip:
            self.player.stop()
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
        self._start_scan(self.settings.library_paths or [self.settings.music_root], "Rescanned", prune=True)

    def _on_yt_download(self, url: str) -> None:
        dlg = YtDownloadDialog(url, self.settings, self.library, self)
        dlg.library_updated.connect(self._library_refresh_timer.start)
        dlg.exec()

    def _search_youtube_for_track(self, query: str) -> None:
        if not query:
            return
        self.tab_bar.setCurrentIndex(self._tab_index["YouTube"])
        if self.youtube_view.search_youtube(query):
            self.statusBar().showMessage(f"Searching YouTube for {query}", 3000)
        elif self.youtube_view.is_searching():
            self.statusBar().showMessage("YouTube search already in progress.", 3000)
        else:
            self.statusBar().showMessage("YouTube search is unavailable.", 3000)

    def _enqueue_tracks(self, tracks: list) -> None:
        self.player.enqueue(tracks)
        count = len(tracks)
        total = len(self.player.queue())
        plural = "" if count == 1 else "s"
        queue_plural = "" if total == 1 else "s"
        self.show_toast(
            f"Enqueued {count} track{plural} — queue now has {total} track{queue_plural}.",
            level="info",
        )

    def _start_scan(self, roots: list[str], label: str, prune: bool = False) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self.show_toast("Library scan already running.", level="warning")
            return
        self._scan_status_label.setText("Scanning library…")
        self._scan_status_label.setVisible(True)
        self._scan_progress.setVisible(True)
        self._scan_thread = _LibraryScanThread(self.library, list(roots), label, prune, self)
        self._scan_thread.finished_with.connect(self._on_scan_finished)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_finished(self, n: int, removed: int, label: str) -> None:
        self._scan_status_label.setVisible(False)
        self._scan_status_label.setText("")
        self._scan_progress.setVisible(False)
        parts = [f"{label}: {n} new track{'' if n == 1 else 's'}"]
        if removed:
            parts.append(f"{removed} removed")
        message = ", ".join(parts)
        toast_level = "success" if (n > 0 or removed > 0) else "info"
        self.show_toast(message, level=toast_level, duration_ms=4000)
        self.library_view.refresh()
        self.video_player_view.refresh_catalog()
        self._scan_thread = None

    def remove_missing(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Remove missing files?",
            "Scan the library for tracks whose files no longer exist on disk and remove them?\n\n"
            "Files on disk are never deleted — only the library's records of missing files.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        n = self.library.remove_missing()
        if n > 0:
            self.show_toast(
                f"Removed {n} missing track{'' if n == 1 else 's'}",
                level="success",
            )
        else:
            self.show_toast("No missing tracks were found.", level="info")
        self.library_view.refresh()

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        old_paths = list(self.settings.library_paths)
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings
            self.settings.save()
            metadata.reset_musicbrainz_useragent()
            self.ripper_view.apply_settings(self.settings)
            self.player.set_equalizer(
                self.settings.equalizer_enabled,
                self.settings.equalizer_bands,
                self.settings.equalizer_preamp,
            )
            self.video_player_view.apply_equalizer(
                self.settings.equalizer_enabled,
                self.settings.equalizer_bands,
                self.settings.equalizer_preamp,
            )
            if self.settings.library_paths != old_paths and self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self.show_toast("Settings saved.", level="success")

    def _maybe_show_first_run(self) -> None:
        if self.settings.first_run_completed:
            return
        dlg = FirstRunDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings
            self.settings.save()
            metadata.reset_musicbrainz_useragent()
            self.ripper_view.apply_settings(self.settings)
            if self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self.show_toast("Setup saved.", level="success")

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
        self.tab_bar.setCurrentIndex(self._tab_index["Library"])
        self.library_view.search.setFocus()
        self.library_view.search.selectAll()

    def open_equalizer(self) -> None:
        if self._equalizer_dialog is None:
            self._equalizer_dialog = EqualizerDialog(self.settings, self)
            self._equalizer_dialog.equalizer_changed.connect(self.player.set_equalizer)
            self._equalizer_dialog.equalizer_changed.connect(self.video_player_view.apply_equalizer)
            self._equalizer_dialog.settings_saved.connect(self._apply_equalizer_settings)
            self._equalizer_dialog.finished.connect(self._clear_equalizer_dialog)
        self._equalizer_dialog.show()
        self._equalizer_dialog.raise_()
        self._equalizer_dialog.activateWindow()

    def _apply_equalizer_settings(self, settings: Settings) -> None:
        self.settings.equalizer_enabled = settings.equalizer_enabled
        self.settings.equalizer_preamp = settings.equalizer_preamp
        self.settings.equalizer_bands = list(settings.equalizer_bands)
        self.settings.equalizer_curve_name = settings.equalizer_curve_name
        self.settings.equalizer_custom_curves = dict(settings.equalizer_custom_curves)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self.video_player_view.apply_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self.show_toast("Equalizer settings saved.", level="success")

    def _clear_equalizer_dialog(self, *_args) -> None:
        self._equalizer_dialog = None

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__} {__version__}</h3>"
            "<p><i>Dedicated to: Chuck Lyon</i></p>"
            "<p>Rip your CDs to FLAC, manage your library, search YouTube, "
            "and play music with a familiar Windows Media Player look.</p>"
            "<p>Uses MusicBrainz, Cover Art Archive, ffmpeg, and yt-dlp.</p>",
        )

    # ------------------------------------------------------------------ drag-and-drop
    _AUDIO_EXTENSIONS = frozenset(
        ".flac .mp3 .ogg .wav .aac .m4a .wma .opus .ape .aiff .alac .mka .mp4 .mkv .webm".split()
    )

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev: QDropEvent) -> None:
        folders: list[str] = []
        files: list[str] = []
        for url in ev.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            from pathlib import Path as _Path
            p = _Path(path)
            if p.is_dir():
                folders.append(path)
            elif p.suffix.lower() in self._AUDIO_EXTENSIONS:
                files.append(path)
        if folders:
            for folder in folders:
                if folder not in self.settings.library_paths:
                    self.settings.library_paths.append(folder)
            self.settings.save()
            self._start_scan(folders, f"Added {len(folders)} folder(s)")
        if files:
            for f in files:
                self.library.add_file(f)
            self.library.commit()
            self.library_view.refresh()
            plural = "" if len(files) == 1 else "s"
            self.show_toast(
                f"Added {len(files)} file{plural} to library.",
                level="success",
            )
        ev.acceptProposedAction()

    def closeEvent(self, ev) -> None:
        self.player.stop()
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.request_stop()
            self._scan_thread.wait()
        self.youtube_view.shutdown()
        self.ripper_view.shutdown()
        self.settings.last_volume = self.player.volume()
        self.settings.save()
        self.video_player_view.cleanup()
        self.player.cleanup()
        self.library.close()
        metadata.shutdown()
        close_cd_dll_handles()
        close_dll_handles()
        super().closeEvent(ev)
