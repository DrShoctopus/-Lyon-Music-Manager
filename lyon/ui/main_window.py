"""Top-level window with native tab bar and stacked views."""
from __future__ import annotations

from collections.abc import Callable
import os

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QStackedWidget, QStatusBar, QTabBar, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core import metadata
from ..core.cd_detect import close_dll_handles as close_cd_dll_handles
from ..core.cast_controller import CastController
from ..core.dlna_server import DlnaServer
from ..core.library import Library, SUPPORTED_EXTS, ScanSummary, Track
from ..core.library_watcher import (
    LibraryFolderWatcher,
    LibraryIndexThread,
    WatchBatch,
    coalesce_batch,
)
from ..core.playback_backend import close_dll_handles
from ..core.podcast import podcast_user_agent
from ..core.radio import radio_user_agent
from ..core.player import Player
from ..core.replaygain import ReplayGainScanner
from ..core.scrobbler import ScrobblerService
from ..core.ripper import find_ffmpeg
from ..core.diagnostics import collect_diagnostics_bundle, logs_dir
from ..core.settings import Settings
from .about_dialog import AboutDialog
from .branding import app_icon
from .diagnostics_dialog import DiagnosticsDialog
from .library_stats_dialog import LibraryStatsDialog
from .duplicate_dialog import DuplicateDialog
from .cast_dialog import CastDialog
from .equalizer_dialog import EqualizerDialog
from .first_run_dialog import FirstRunDialog
from .library_view import LibraryView
from .transport_bar import TransportBar
from .queue_dialog import QueueDialog
from .styles import apply_app_styles
from .toast import Toast
from .yt_download_dialog import YtDownloadDialog


class _LibraryScanThread(QThread):
    finished_with = Signal(int, int, int, str)  # (new_tracks, updated_tracks, removed_tracks, label)
    failed_with = Signal(str, str)         # (label, error)

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
        self.requestInterruption()

    def run(self) -> None:
        try:
            should_cancel = lambda: self._cancel or self.isInterruptionRequested()
            summary = ScanSummary()
            summary.removed = (
                self.library.remove_missing_under_existing_roots(self.roots)
                if self.prune and not should_cancel()
                else 0
            )
            scan_summary = (
                self.library.scan_paths_summary(self.roots, should_cancel=should_cancel)
                if not should_cancel()
                else ScanSummary()
            )
            summary.merge(scan_summary)
            self.finished_with.emit(summary.added, summary.updated, summary.removed, self.label)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self.failed_with.emit(self.label, str(exc))


class MainWindow(QMainWindow):
    # Tab display order — index matches the QStackedWidget page index.
    _TAB_ORDER = ("Library", "Now Playing", "Podcasts", "Radio", "Video", "Disc", "Rip", "YouTube")
    _TAB_SHORTCUTS = {
        "Library": "Ctrl+1",
        "Now Playing": "Ctrl+2",
        "Radio": "Ctrl+3",
        "Video": "Ctrl+4",
        "Disc": "Ctrl+5",
        "Rip": "Ctrl+6",
        "YouTube": "Ctrl+7",
        "Podcasts": "Ctrl+8",
    }

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self, library=self.library)
        self.player.set_volume(self.settings.last_volume)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self.player.set_crossfade(self.settings.crossfade_seconds)
        self.player.set_replaygain(
            self.settings.replaygain_mode,
            self.settings.replaygain_preamp_db,
            self.settings.replaygain_prevent_clipping,
        )
        self.player.set_audio_device(
            self.settings.audio_output,
            self.settings.audio_output_device,
        )
        self.player.set_gapless(self.settings.gapless_playback)
        self.scrobbler = ScrobblerService(self.player, self.settings, self)
        self.dlna_server = DlnaServer(self.library, self.settings)
        self.cast_controller = CastController(self)
        self.cast_controller.cast_started.connect(self._on_cast_started)
        self.cast_controller.cast_stopped.connect(self._on_cast_stopped)
        self.cast_controller.cast_error.connect(
            lambda msg: self.show_toast(msg, level="warning")
        )
        self.cast_controller.cast_playback_state_changed.connect(
            self._on_cast_playback_state_changed
        )
        self._scan_thread: _LibraryScanThread | None = None
        self._rg_scanner: ReplayGainScanner | None = None
        self._watch_index_thread: LibraryIndexThread | None = None
        self._library_watcher = LibraryFolderWatcher(self)
        self._watch_pending = WatchBatch()
        self._watcher_unavailable_notified = False
        self._equalizer_dialog: EqualizerDialog | None = None
        self._queue_dialog: QueueDialog | None = None
        self._cast_dialog: CastDialog | None = None
        self._current_toast: Toast | None = None
        self._now_playing_view = None
        self._podcast_view = None
        self._radio_view = None
        # Remembered most recently requested radio (url, title) for friendly
        # error reporting; cleared once a different source plays.
        self._last_radio_request: tuple[str, str] | None = None
        # YouTube acknowledgement: tracks the last tab the user actually
        # confirmed so we can revert there if they decline the gate.
        self._last_confirmed_tab_idx: int = 0
        # Auto-update plumbing — see _maybe_check_for_update / check_for_updates_now.
        self._update_thread = None  # type: ignore[assignment]
        self._update_worker = None  # type: ignore[assignment]
        self._update_dialog = None  # type: ignore[assignment]
        self._update_manual_request: bool = False
        self._youtube_view = None
        self._disc_view = None
        self._ripper_view = None
        self._video_player_view = None
        self._tab_placeholders: dict[str, QWidget] = {}
        # Debounce rapid library_updated signals (e.g. playlist downloads).
        self._library_refresh_timer = QTimer(self)
        self._library_refresh_timer.setSingleShot(True)
        self._library_refresh_timer.setInterval(300)
        self._watch_debounce_timer = QTimer(self)
        self._watch_debounce_timer.setSingleShot(True)
        self._watch_debounce_timer.setInterval(750)
        self._watch_debounce_timer.timeout.connect(self._flush_library_watch_events)
        # Sleep timer
        self._sleep_remaining_s = 0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(1000)
        self._sleep_timer.timeout.connect(self._on_sleep_tick)

        self.setWindowTitle(__app_name__)
        self.setWindowIcon(app_icon())
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        apply_app_styles(self)

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

        self._cast_btn: QToolButton | None = None
        for label, tooltip, handler in (
            ("Queue",    "Show playback queue  [Ctrl+Q]", self.open_queue),
            ("EQ",       "Open 10-band equalizer",        self.open_equalizer),
            ("Cast",     "Cast to a local device",        self.open_cast_dialog),
            ("Settings", "Open Settings",                 self.open_settings),
        ):
            btn = QToolButton()
            btn.setText(label)
            btn.setToolTip(tooltip)
            btn.setObjectName("navToolBtn")
            btn.clicked.connect(handler)
            hlayout.addWidget(btn)
            if label == "Cast":
                self._cast_btn = btn

        self._sleep_btn = QToolButton()
        self._sleep_btn.setText("Sleep")
        self._sleep_btn.setToolTip("Sleep timer — stop playback after a set time")
        self._sleep_btn.setObjectName("navToolBtn")
        self._sleep_menu = QMenu(self._sleep_btn)
        for mins in (15, 30, 45, 60):
            act = self._sleep_menu.addAction(f"{mins} minutes")
            act.setData(mins * 60)
        self._sleep_menu.addSeparator()
        custom_act = self._sleep_menu.addAction("Custom…")
        custom_act.setData(-1)
        self._sleep_menu.addSeparator()
        self._sleep_cancel_act = self._sleep_menu.addAction("Cancel Timer")
        self._sleep_cancel_act.setEnabled(False)
        self._sleep_menu.triggered.connect(self._on_sleep_menu)
        self._sleep_btn.setMenu(self._sleep_menu)
        self._sleep_btn.setPopupMode(QToolButton.InstantPopup)
        hlayout.addWidget(self._sleep_btn)

        layout.addWidget(header)

        # ---- stacked content (order must match _TAB_ORDER)
        self.stack = QStackedWidget()
        self.library_view = LibraryView(self.library)
        self._library_refresh_timer.timeout.connect(self.library_view.refresh)
        self._library_refresh_timer.timeout.connect(self._refresh_video_catalog_if_loaded)

        # Build tab bar + stack together so indices always match _TAB_ORDER.
        _tab_views = {
            "Library": self.library_view,
            "Now Playing": self._placeholder_page("Now Playing"),
            "Podcasts": self._placeholder_page("Podcasts"),
            "Radio": self._placeholder_page("Radio"),
            "Video": self._placeholder_page("Video"),
            "Disc": self._placeholder_page("Disc"),
            "Rip": self._placeholder_page("Rip"),
            "YouTube": self._placeholder_page("YouTube"),
        }
        self._tab_index: dict[str, int] = {}
        for idx, name in enumerate(self._TAB_ORDER):
            self.tab_bar.addTab(name)
            self.stack.addWidget(_tab_views[name])
            self._tab_index[name] = idx

        self.tab_bar.currentChanged.connect(self._activate_tab)
        self.stack.currentChanged.connect(self._on_view_changed)
        layout.addWidget(self.stack, 1)

        # ---- transport bar
        self.transport = TransportBar(self.player, library=self.library)
        self.transport.open_now_playing.connect(
            lambda: self.tab_bar.setCurrentIndex(self._tab_index["Now Playing"]))
        self.transport.play_requested.connect(self._on_transport_play_requested)
        self.transport.previous_requested.connect(self._on_transport_previous_requested)
        self.transport.next_requested.connect(self._on_transport_next_requested)
        self.transport.stop_requested.connect(self._on_transport_stop_requested)
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
        self.library_view.play_video.connect(self._play_library_video)
        self.library_view.enqueue_tracks.connect(self._enqueue_tracks)
        self.library_view.status_message.connect(
            lambda m: self.show_toast(m, level="warning"))
        self.player.track_changed.connect(self.library_view.highlight_track)
        self.player.playback_unavailable.connect(self._on_playback_unavailable)
        self._connect_backend_error_toast()
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_youtube_search.connect(self._search_youtube_for_track)
        self.library_view.request_open_settings.connect(self.open_settings)
        self.library_view.request_diagnostics.connect(self.show_diagnostics)
        self.library_view.request_scan_replaygain.connect(self._on_scan_replaygain)
        self._library_watcher.paths_changed.connect(self._on_watched_paths_changed)
        self._library_watcher.paths_deleted.connect(self._on_watched_paths_deleted)
        self._library_watcher.paths_moved.connect(self._on_watched_paths_moved)
        self._library_watcher.folders_moved.connect(self._on_watched_folders_moved)
        self._library_watcher.folders_changed.connect(self._on_watched_folders_changed)
        self._library_watcher.watch_error.connect(self._on_library_watch_error)

        self.setAcceptDrops(True)

        # Initial scan of saved roots.
        if self.settings.library_paths and self.settings.first_run_completed:
            self._start_scan(self.settings.library_paths, "Scanned", prune=True)

        # Menu + keyboard shortcuts
        self._build_menu()
        self._restart_library_watcher()
        self._restart_dlna_server(show_toast=False)

        # Ensure transport visibility matches initial tab (Library, index 0).
        self._on_view_changed(0)

        # Restore previous queue (no auto-play)
        if self.settings.queue_track_paths:
            restored = self.library.tracks_for_paths(self.settings.queue_track_paths)
            if restored:
                self.player.load_queue(
                    restored,
                    min(self.settings.queue_current_index, len(restored) - 1),
                )

        # Platform global media keys (optional dependencies; no-op when unavailable)
        from ..core.media_keys import register_media_key_handler
        self._media_key_handler = register_media_key_handler(self.player)

        QTimer.singleShot(0, self._maybe_show_first_run)
        # Auto-update check kicks in shortly after first-run resolves; deferring
        # a couple of seconds keeps the splash + startup-scan responsive.
        QTimer.singleShot(2500, self._maybe_check_for_update)
        # One-time SmartScreen advisory for installer-installed unsigned builds.
        QTimer.singleShot(1500, self._maybe_show_smartscreen_advisory)
        backup_path = self.settings.corrupt_backup_path
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
        file_menu.addAction(QAction("Find Duplicates…", self,
                                    triggered=self.show_duplicates))
        file_menu.addSeparator()
        exit_act = QAction("Exit", self, triggered=self.close)
        exit_act.setMenuRole(QAction.MenuRole.QuitRole)
        file_menu.addAction(exit_act)

        playback_menu = m.addMenu("&Playback")
        play_action = QAction("Play/Pause", self, triggered=self._on_transport_play_requested)
        play_action.setShortcut("Ctrl+Space")
        playback_menu.addAction(play_action)
        prev_action = QAction("Previous", self, triggered=self._on_transport_previous_requested)
        prev_action.setShortcut("Ctrl+Left")
        playback_menu.addAction(prev_action)
        next_action = QAction("Next", self, triggered=self._on_transport_next_requested)
        next_action.setShortcut("Ctrl+Right")
        playback_menu.addAction(next_action)
        queue_action = QAction("Show Queue", self, triggered=self.open_queue)
        queue_action.setShortcut("Ctrl+Q")
        playback_menu.addAction(queue_action)
        search_action = QAction("Focus Library Search", self, triggered=self._focus_library_search)
        search_action.setShortcut("Ctrl+F")
        playback_menu.addAction(search_action)
        jump_action = QAction("Jump to Now Playing", self, triggered=self._jump_to_now_playing)
        jump_action.setShortcut("Ctrl+L")
        playback_menu.addAction(jump_action)

        # View menu shortcuts preserve the historical tab accelerators even if
        # the visual tab order changes.
        view_menu = m.addMenu("&View")
        for name in self._TAB_ORDER:
            act = QAction(name, self)
            act.setShortcut(self._TAB_SHORTCUTS[name])
            act.triggered.connect(
                lambda checked=False, i=self._tab_index[name]: self.tab_bar.setCurrentIndex(i)
            )
            view_menu.addAction(act)

        settings_menu = m.addMenu("&Settings")
        settings_act = QAction("Open Settings", self, triggered=self.open_settings)
        settings_act.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        settings_menu.addAction(settings_act)

        help_menu = m.addMenu("&Help")
        kb_act = QAction("Knowledge Base", self, triggered=self.show_knowledge_base)
        kb_act.setShortcut("F1")
        help_menu.addAction(kb_act)
        help_menu.addAction(QAction("Library Statistics", self, triggered=self.show_library_stats))
        help_menu.addAction(QAction("Runtime Diagnostics", self, triggered=self.show_diagnostics))
        help_menu.addSeparator()
        help_menu.addAction(QAction("Open Log Folder", self, triggered=self.open_log_folder))
        help_menu.addAction(QAction(
            "Copy Diagnostics to Clipboard", self, triggered=self.copy_diagnostics
        ))
        help_menu.addSeparator()
        help_menu.addAction(QAction(
            "Check for Updates…", self, triggered=self.check_for_updates_now
        ))
        help_menu.addSeparator()
        about_act = QAction("About", self, triggered=self.show_about)
        about_act.setMenuRole(QAction.MenuRole.AboutRole)
        help_menu.addAction(about_act)

    # ------------------------------------------------------------------ tabs

    @property
    def podcast_view(self):
        return self._ensure_tab_view("Podcasts")

    @property
    def now_playing(self):
        return self._ensure_tab_view("Now Playing")

    @property
    def radio_view(self):
        return self._ensure_tab_view("Radio")

    @property
    def youtube_view(self):
        return self._ensure_tab_view("YouTube")

    @property
    def disc_view(self):
        return self._ensure_tab_view("Disc")

    @property
    def ripper_view(self):
        return self._ensure_tab_view("Rip")

    @property
    def video_player_view(self):
        return self._ensure_tab_view("Video")

    def _placeholder_page(self, name: str) -> QWidget:
        page = QWidget()
        page.setObjectName(f"lazy{name.replace(' ', '')}Placeholder")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(f"Loading {name}...")
        label.setObjectName("mutedText")
        layout.addWidget(label)
        self._tab_placeholders[name] = page
        return page

    def _activate_tab(self, idx: int) -> None:
        if not (0 <= idx < len(self._TAB_ORDER)):
            return
        name = self._TAB_ORDER[idx]
        if name == "YouTube" and not self._ensure_youtube_acknowledged():
            # Revert the tab bar back to the last confirmed tab. Defer
            # via QTimer so the signal completes before we re-emit.
            revert_idx = self._last_confirmed_tab_idx
            if revert_idx == idx:
                revert_idx = 0
            QTimer.singleShot(0, lambda r=revert_idx: self.tab_bar.setCurrentIndex(r))
            return
        self._ensure_tab_view(name)
        self._last_confirmed_tab_idx = idx
        self.stack.setCurrentIndex(idx)

    def _ensure_tab_view(self, name: str) -> QWidget:
        if name == "Now Playing":
            if self._now_playing_view is None:
                from .now_playing import NowPlayingView

                view = NowPlayingView(
                    self.player,
                    library=self.library,
                    settings=self.settings,
                )
                view.request_edit_metadata.connect(self.library_view.edit_track_metadata)
                self._now_playing_view = self._replace_tab_widget(name, view)
            return self._now_playing_view
        if name == "Podcasts":
            if self._podcast_view is None:
                from .podcast_view import PodcastView

                view = PodcastView(self.settings)
                view.play_requested.connect(self._play_podcast_episode)
                view.status_message.connect(lambda m: self.show_toast(m, level="info"))
                self._podcast_view = self._replace_tab_widget(name, view)
            return self._podcast_view
        if name == "Radio":
            if self._radio_view is None:
                from .radio_view import RadioView

                view = RadioView(self.settings)
                view.play_requested.connect(self._play_radio_station)
                view.status_message.connect(lambda m: self.show_toast(m, level="success"))
                self._radio_view = self._replace_tab_widget(name, view)
            return self._radio_view
        if name == "YouTube":
            if self._youtube_view is None:
                from .youtube_view import YouTubeView

                view = YouTubeView()
                view.download_requested.connect(self._on_yt_download)
                self._youtube_view = self._replace_tab_widget(name, view)
            return self._youtube_view
        if name == "Video":
            if self._video_player_view is None:
                from .video_player_view import VideoPlayerView

                view = VideoPlayerView(
                    library=self.library,
                    initial_volume=self.settings.last_volume,
                    settings=self.settings,
                )
                view.apply_equalizer(
                    self.settings.equalizer_enabled,
                    self.settings.equalizer_bands,
                    self.settings.equalizer_preamp,
                )
                view.request_diagnostics.connect(self.show_diagnostics)
                view.resume_available.connect(self._on_video_resume_available)
                self._video_player_view = self._replace_tab_widget(name, view)
            return self._video_player_view
        if name == "Disc":
            if self._disc_view is None:
                from .disc_view import DiscView

                view = DiscView(self.settings)
                view.play_audio_tracks.connect(self._play_disc_audio_tracks)
                view.enqueue_audio_tracks.connect(self._enqueue_disc_audio_tracks)
                view.play_video_disc.connect(self._play_video_disc)
                view.stop_video_disc.connect(self._stop_video_playback_if_loaded)
                view.rip_drive_requested.connect(self._rip_disc_drive)
                view.status_message.connect(lambda m: self.show_toast(m, level="info"))
                self._disc_view = self._replace_tab_widget(name, view)
            return self._disc_view
        if name == "Rip":
            if self._ripper_view is None:
                from .ripper_view import RipperView

                view = RipperView(self.settings, self.library)
                view.rip_completed.connect(self.library_view.refresh)
                view.log.connect(lambda m: self.statusBar().showMessage(m, 4000))
                self._ripper_view = self._replace_tab_widget(name, view)
            return self._ripper_view
        return self.stack.widget(self._tab_index[name])

    def _replace_tab_widget(self, name: str, view: QWidget) -> QWidget:
        idx = self._tab_index[name]
        old = self.stack.widget(idx)
        self.stack.removeWidget(old)
        self.stack.insertWidget(idx, view)
        old.deleteLater()
        if self.tab_bar.currentIndex() == idx or self.stack.currentIndex() == idx:
            self.stack.setCurrentIndex(idx)
        return view

    def _refresh_video_catalog_if_loaded(self) -> None:
        if self._video_player_view is not None:
            self._video_player_view.refresh_catalog()

    def _pause_video_playback_if_loaded(self) -> None:
        if self._video_player_view is not None:
            self._video_player_view.pause_playback()

    def _stop_video_playback_if_loaded(self) -> None:
        if self._video_player_view is not None:
            self._video_player_view.stop_playback()

    def _apply_video_equalizer_if_loaded(
        self,
        enabled: bool,
        bands: list[float],
        preamp: float,
    ) -> None:
        if self._video_player_view is not None:
            self._video_player_view.apply_equalizer(enabled, bands, preamp)

    def _apply_video_settings_if_loaded(self) -> None:
        if self._video_player_view is not None:
            self._video_player_view.apply_settings(self.settings)

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
        if self.cast_controller.is_casting:
            self.cast_controller.toggle_play_pause()
            return
        if self.stack.currentWidget() is self.library_view and not self.player.is_playing():
            playback = self.library_view.highlighted_playback()
            if playback is not None:
                tracks, start_index = playback
                self.player.set_queue(tracks, start_index)
                return
        self.player.toggle()

    def _on_transport_previous_requested(self) -> None:
        if self.cast_controller.is_casting:
            self.cast_controller.previous_track()
            return
        self.player.previous()

    def _on_transport_next_requested(self) -> None:
        if self.cast_controller.is_casting:
            self.cast_controller.next_track()
            return
        self.player.next()

    def _on_transport_stop_requested(self) -> None:
        if self.cast_controller.is_casting:
            self.cast_controller.stop_cast()
            return
        self.player.stop()

    def _on_playback_unavailable(self, reason: str) -> None:
        self.show_toast(
            "Audio playback requires VLC/libVLC. Run diagnostics for setup details.",
            level="error",
            duration_ms=6000,
            action=("Diagnostics", self.show_diagnostics),
        )
        self.statusBar().showMessage(reason, 6000)

    def _connect_backend_error_toast(self) -> None:
        """Subscribe to backend ``error_occurred`` to surface stream failures."""
        backend = getattr(self.player, "_backend", None)
        signal = getattr(backend, "error_occurred", None)
        if signal is None:
            return
        try:
            signal.connect(self._on_stream_error)
        except (RuntimeError, TypeError):
            pass

    def _on_stream_error(self, url: str) -> None:
        last = self._last_radio_request
        if last is None or last[0] != url:
            return
        _, title = last
        self.show_toast(
            f'Could not connect to "{title}".',
            level="error",
            duration_ms=5000,
        )

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
        current_index = self.stack.currentIndex()
        is_rip = current_index == self._tab_index["Rip"]
        is_video = current_index == self._tab_index["Video"]
        self.transport.setVisible(not is_rip and not is_video)
        if current is self.library_view:
            self.library_view.refresh_playlists()
        if is_rip:
            self.player.stop()
        if is_video and self.player.is_playing():
            self.player.pause()
        if not is_video:
            self._pause_video_playback_if_loaded()

    # ------------------------------------------------------------------ actions
    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add music folder")
        if not folder:
            return
        if folder not in self.settings.library_paths:
            self.settings.library_paths.append(folder)
            self.settings.save()
            self._restart_library_watcher()
        self._start_scan([folder], f"Added tracks from {folder}")

    def rescan(self) -> None:
        self._start_scan(self.settings.library_paths or [self.settings.music_root], "Rescanned", prune=True)

    def _on_scan_replaygain(self, tracks: list) -> None:
        if self._rg_scanner is not None and self._rg_scanner.isRunning():
            self.show_toast("ReplayGain scan already in progress.", level="warning")
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.show_toast(
                "ffmpeg not found — ReplayGain scan requires ffmpeg.", level="error"
            )
            return
        paths = [t.path for t in tracks if getattr(t, "path", None)]
        if not paths:
            return
        album_mode = self.settings.replaygain_mode == "album"
        count = len(paths)
        noun = "track" if count == 1 else "tracks"
        self.show_toast(f"Scanning {count} {noun} for ReplayGain…", level="info")
        self._rg_scanner = ReplayGainScanner(paths, ffmpeg, album_mode=album_mode, parent=self)
        self._rg_scanner.finished_scanning.connect(self._on_rg_scan_finished)
        self._rg_scanner.start()

    def _on_rg_scan_finished(self, written: int, failed: int) -> None:
        if failed:
            self.show_toast(
                f"ReplayGain scan complete: {written} tagged, {failed} failed.", level="warning"
            )
        else:
            self.show_toast(f"ReplayGain scan complete: {written} tracks tagged.", level="success")
        if self._rg_scanner is not None:
            self._rg_scanner.deleteLater()
            self._rg_scanner = None

    def _on_yt_download(self, url: str) -> None:
        if not self._ensure_youtube_acknowledged():
            return
        dlg = YtDownloadDialog(url, self.settings, self.library, self)
        dlg.library_updated.connect(self._library_refresh_timer.start)
        dlg.video_download_finished.connect(self._on_yt_video_download_finished)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _ensure_youtube_acknowledged(self) -> bool:
        """Show the YouTube ToS gate if the user has not already accepted.

        Returns True if the user has previously acknowledged or accepts now,
        False if they declined this prompt. Persists the flag to
        ``settings.json`` on first accept.
        """
        if self.settings.youtube_acknowledged:
            return True
        from .youtube_acknowledgement_dialog import YouTubeAcknowledgementDialog

        dlg = YouTubeAcknowledgementDialog(self)
        try:
            accepted = dlg.exec() == dlg.DialogCode.Accepted and dlg.acknowledged
        finally:
            dlg.deleteLater()
        if not accepted:
            return False
        self.settings.youtube_acknowledged = True
        self.settings.save()
        return True

    def _on_yt_video_download_finished(self) -> None:
        self.tab_bar.setCurrentIndex(self._tab_index["Video"])
        self.video_player_view.refresh_catalog()
        self._library_refresh_timer.start()

    def _search_youtube_for_track(self, query: str) -> None:
        if not query:
            return
        if not self._ensure_youtube_acknowledged():
            return
        self.tab_bar.setCurrentIndex(self._tab_index["YouTube"])
        youtube_view = self.youtube_view
        if youtube_view.search_youtube(query):
            self.show_toast(f"Searching YouTube for {query}", level="info")
        elif youtube_view.is_searching():
            self.show_toast("YouTube search already in progress.", level="warning")
        else:
            self.show_toast("YouTube search is unavailable.", level="error")

    def _play_radio_station(self, url: str, title: str) -> None:
        self._pause_video_playback_if_loaded()
        self._last_radio_request = (url, title)
        self.player.play_url(
            url,
            title=title,
            options=(
                f":http-user-agent={radio_user_agent()}",
                ":network-caching=2000",
                ":http-reconnect",
            ),
        )
        self.show_toast(f"Playing radio: {title}", level="info")

    def _play_podcast_episode(self, url: str, title: str) -> None:
        self._pause_video_playback_if_loaded()
        self.player.play_url(
            url,
            title=title,
            options=(
                f":http-user-agent={podcast_user_agent()}",
                ":network-caching=1500",
            ),
        )
        self.show_toast(f"Playing podcast: {title}", level="info")

    def _on_video_resume_available(self, message: str, callback: object) -> None:
        if not callable(callback):
            return
        self.show_toast(
            message,
            level="info",
            duration_ms=7000,
            action=("Resume", callback),
        )

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
        if self._watch_index_thread is not None and self._watch_index_thread.isRunning():
            self.show_toast("Library update already running.", level="warning")
            return
        self._scan_status_label.setText("Scanning library…")
        self._scan_status_label.setVisible(True)
        self._scan_progress.setVisible(True)
        self._scan_thread = _LibraryScanThread(self.library, list(roots), label, prune, self)
        self._scan_thread.finished_with.connect(self._on_scan_finished)
        self._scan_thread.failed_with.connect(self._on_scan_failed)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_finished(self, n: int, updated: int, removed: int, label: str) -> None:
        self._scan_status_label.setVisible(False)
        self._scan_status_label.setText("")
        self._scan_progress.setVisible(False)
        parts = [f"{label}: {n} new track{'' if n == 1 else 's'}"]
        if updated:
            parts.append(f"{updated} updated")
        if removed:
            parts.append(f"{removed} removed")
        message = ", ".join(parts)
        toast_level = "success" if (n > 0 or updated > 0 or removed > 0) else "info"
        self.show_toast(message, level=toast_level, duration_ms=4000)
        self.dlna_server.invalidate_cache()
        self.library_view.refresh()
        self._refresh_video_catalog_if_loaded()
        self._scan_thread = None

    def _on_scan_failed(self, label: str, error: str) -> None:
        self._scan_status_label.setVisible(False)
        self._scan_status_label.setText("")
        self._scan_progress.setVisible(False)
        self.show_toast(f"{label} failed: {error}", level="error", duration_ms=6000)
        self._scan_thread = None

    # ------------------------------------------------------------------ watched folders
    def _restart_library_watcher(self) -> None:
        self._library_watcher.stop()
        if not self.settings.watch_library_folders or not self.settings.library_paths:
            return
        if not LibraryFolderWatcher.is_available():
            if not self._watcher_unavailable_notified:
                self.statusBar().showMessage(
                    "Install watchdog to enable watched library folders.",
                    6000,
                )
                self._watcher_unavailable_notified = True
            return
        self._library_watcher.start(self.settings.library_paths)

    def _on_library_watch_error(self, message: str) -> None:
        if not message:
            return
        self.statusBar().showMessage(message, 6000)

    def _on_watched_paths_changed(self, paths: list) -> None:
        self._queue_library_watch_batch(
            WatchBatch(changed_paths={str(path) for path in paths})
        )

    def _on_watched_paths_deleted(self, paths: list) -> None:
        self._queue_library_watch_batch(
            WatchBatch(deleted_paths={str(path) for path in paths})
        )

    def _on_watched_paths_moved(self, pairs: list) -> None:
        moved: dict[str, str] = {}
        for pair in pairs:
            try:
                old_path, new_path = pair
            except (TypeError, ValueError):
                continue
            moved[str(old_path)] = str(new_path)
        self._queue_library_watch_batch(WatchBatch(moved_paths=moved))

    def _on_watched_folders_changed(self, paths: list) -> None:
        self._queue_library_watch_batch(
            WatchBatch(scan_roots={str(path) for path in paths})
        )

    def _on_watched_folders_moved(self, pairs: list) -> None:
        moved: dict[str, str] = {}
        for pair in pairs:
            try:
                old_path, new_path = pair
            except (TypeError, ValueError):
                continue
            moved[str(old_path)] = str(new_path)
        self._queue_library_watch_batch(WatchBatch(moved_folders=moved))

    def _queue_library_watch_batch(self, batch: WatchBatch) -> None:
        batch = self._filter_watch_batch_to_current_roots(batch)
        if batch.is_empty() or not self.settings.watch_library_folders:
            return
        coalesce_batch(self._watch_pending, batch)
        self._watch_debounce_timer.start()

    def _filter_watch_batch_to_current_roots(self, batch: WatchBatch) -> WatchBatch:
        filtered = WatchBatch()
        for path in batch.changed_paths:
            if self._path_is_under_library_roots(path):
                filtered.changed_paths.add(path)
        for path in batch.deleted_paths:
            if self._path_is_under_library_roots(path):
                filtered.deleted_paths.add(path)
        for path in batch.scan_roots:
            if self._path_is_under_library_roots(path):
                filtered.scan_roots.add(path)
        for old_path, new_path in batch.moved_paths.items():
            old_in = self._path_is_under_library_roots(old_path)
            new_in = self._path_is_under_library_roots(new_path)
            if old_in and new_in:
                filtered.moved_paths[old_path] = new_path
            elif old_in:
                filtered.deleted_paths.add(old_path)
            elif new_in:
                filtered.changed_paths.add(new_path)
        for old_path, new_path in batch.moved_folders.items():
            old_in = self._path_is_under_library_roots(old_path)
            new_in = self._path_is_under_library_roots(new_path)
            if old_in and new_in:
                filtered.moved_folders[old_path] = new_path
            elif old_in:
                filtered.deleted_paths.add(old_path)
            elif new_in:
                filtered.scan_roots.add(new_path)
        return filtered

    def _path_is_under_library_roots(self, path: str) -> bool:
        if not path:
            return False
        try:
            path_norm = os.path.normcase(os.path.abspath(path))
        except OSError:
            return False
        for root in self.settings.library_paths:
            if not root:
                continue
            try:
                root_norm = os.path.normcase(os.path.abspath(root))
                if os.path.commonpath([root_norm, path_norm]) == root_norm:
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _flush_library_watch_events(self) -> None:
        if self._watch_pending.is_empty():
            return
        if self._ripper_is_running():
            self._watch_debounce_timer.start(1500)
            return
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._watch_debounce_timer.start(1000)
            return
        if self._watch_index_thread is not None and self._watch_index_thread.isRunning():
            self._watch_debounce_timer.start(1000)
            return

        batch = self._watch_pending
        self._watch_pending = WatchBatch()
        self._scan_status_label.setText("Updating library…")
        self._scan_status_label.setVisible(True)
        self._scan_progress.setVisible(True)
        self._watch_index_thread = LibraryIndexThread(
            self.library,
            batch,
            settle_ms=750,
            parent=self,
        )
        self._watch_index_thread.finished_with.connect(self._on_watch_index_finished)
        self._watch_index_thread.failed_with.connect(self._on_watch_index_failed)
        self._watch_index_thread.finished.connect(self._watch_index_thread.deleteLater)
        self._watch_index_thread.start()

    def _on_watch_index_finished(self, summary: ScanSummary) -> None:
        self._scan_status_label.setVisible(False)
        self._scan_status_label.setText("")
        self._scan_progress.setVisible(False)
        parts: list[str] = []
        if summary.added:
            parts.append(f"{summary.added} new")
        if summary.updated:
            parts.append(f"{summary.updated} updated")
        if summary.removed:
            parts.append(f"{summary.removed} removed")
        if summary.failed:
            parts.append(f"{summary.failed} failed")
        if parts:
            self.show_toast(
                "Library updated: " + ", ".join(parts),
                level="warning" if summary.failed else "success",
                duration_ms=4000,
            )
            self.dlna_server.invalidate_cache()
            self._library_refresh_timer.start()
        self._watch_index_thread = None

    def _on_watch_index_failed(self, error: str) -> None:
        self._scan_status_label.setVisible(False)
        self._scan_status_label.setText("")
        self._scan_progress.setVisible(False)
        self.show_toast(f"Library update failed: {error}", level="error", duration_ms=6000)
        self._watch_index_thread = None

    def _ripper_is_running(self) -> bool:
        ripper_view = self._ripper_view
        if ripper_view is None:
            return False
        ripper = getattr(ripper_view, "ripper", None)
        if ripper is None:
            return False
        try:
            return bool(ripper.is_running())
        except RuntimeError:
            return False

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
        self.dlna_server.invalidate_cache()
        self.library_view.refresh()

    def _play_disc_audio_tracks(self, tracks: list, start_index: int) -> None:
        self._pause_video_playback_if_loaded()
        self.player.set_queue(tracks, start_index)

    def _enqueue_disc_audio_tracks(self, tracks: list) -> None:
        self.player.enqueue(tracks)
        self.show_toast(f"Enqueued {len(tracks)} disc track(s).", level="success")

    def _play_library_video(self, track: Track) -> None:
        video_view = self.video_player_view
        if not video_view.playback_available():
            reason = video_view.unavailable_reason() or "VLC video playback is unavailable."
            self.show_toast(
                "Video playback requires VLC/libVLC. Run diagnostics for setup details.",
                level="error",
                duration_ms=6000,
                action=("Diagnostics", self.show_diagnostics),
            )
            self.statusBar().showMessage(reason, 6000)
            return
        self.player.stop()
        self.tab_bar.setCurrentIndex(self._tab_index["Video"])
        QTimer.singleShot(0, lambda: video_view.load_path(track.path))

    def _play_video_disc(self, source) -> None:
        video_view = self.video_player_view
        if not video_view.playback_available():
            reason = video_view.unavailable_reason() or "VLC video playback is unavailable."
            self.show_toast(
                "Video disc playback requires VLC/libVLC. Run diagnostics for setup details.",
                level="error",
                duration_ms=6000,
                action=("Diagnostics", self.show_diagnostics),
            )
            self.statusBar().showMessage(reason, 6000)
            return
        self.player.stop()
        self.tab_bar.setCurrentIndex(self._tab_index["Video"])
        QTimer.singleShot(
            0,
            lambda: video_view.load_location(source.uri, label=source.label),
        )
        if source.fallback_uri:
            self.show_toast(
                "If the disc menu does not open, retry with Play Without Menus from Disc.",
                level="info",
                duration_ms=5000,
            )

    def _rip_disc_drive(self, drive: str) -> None:
        if drive:
            self.settings.cd_drive = drive
            self.ripper_view.drive_combo.setCurrentText(drive)
        toc, album = (
            self._disc_view.current_audio_disc()
            if self._disc_view is not None
            else (None, None)
        )
        if toc is not None and (not drive or toc.drive == drive):
            self.ripper_view.load_detected_disc(toc, album)
        self.tab_bar.setCurrentIndex(self._tab_index["Rip"])

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        old_paths = list(self.settings.library_paths)
        old_watch = self.settings.watch_library_folders
        old_dlna = (
            self.settings.dlna_enabled,
            self.settings.dlna_port,
            self.settings.dlna_friendly_name,
        )
        audio_outputs = self.player.list_audio_outputs()
        audio_devices_map: dict[str, list[tuple[str, str]]] = {}
        for out_id, _desc in audio_outputs:
            audio_devices_map[out_id] = self.player.list_audio_devices(out_id)
        dlg = SettingsDialog(
            self.settings, self,
            audio_outputs=audio_outputs,
            audio_devices_map=audio_devices_map,
            scrobbler=self.scrobbler,
        )
        try:
            accepted = dlg.exec()
            result_settings = dlg.result_settings if accepted else None
        finally:
            dlg.deleteLater()
        if accepted and result_settings is not None:
            if (
                result_settings.dlna_enabled
                and not old_dlna[0]
                and not self._confirm_dlna_lan_exposure()
            ):
                result_settings.dlna_enabled = False
            self.settings = result_settings
            self.settings.save()
            metadata.reset_musicbrainz_useragent()
            metadata.clear_metadata_cache()   # evict stale entries if API key changed
            if self._ripper_view is not None:
                self._ripper_view.apply_settings(self.settings)
            if self._now_playing_view is not None:
                self._now_playing_view._settings = self.settings
            self._apply_video_settings_if_loaded()
            if self._podcast_view is not None:
                self._podcast_view.apply_settings(self.settings)
            if self._radio_view is not None:
                self._radio_view.apply_settings(self.settings)
            self.player.set_equalizer(
                self.settings.equalizer_enabled,
                self.settings.equalizer_bands,
                self.settings.equalizer_preamp,
            )
            self.player.set_crossfade(self.settings.crossfade_seconds)
            self.player.set_replaygain(
                self.settings.replaygain_mode,
                self.settings.replaygain_preamp_db,
                self.settings.replaygain_prevent_clipping,
            )
            self.player.set_audio_device(
                self.settings.audio_output,
                self.settings.audio_output_device,
            )
            self.player.set_gapless(self.settings.gapless_playback)
            self.scrobbler.update_settings(self.settings)
            new_dlna = (
                self.settings.dlna_enabled,
                self.settings.dlna_port,
                self.settings.dlna_friendly_name,
            )
            if new_dlna != old_dlna:
                self._restart_dlna_server(show_toast=True)
            self._apply_video_equalizer_if_loaded(
                self.settings.equalizer_enabled,
                self.settings.equalizer_bands,
                self.settings.equalizer_preamp,
            )
            paths_changed = self.settings.library_paths != old_paths
            watch_changed = self.settings.watch_library_folders != old_watch
            if paths_changed or watch_changed:
                self._restart_library_watcher()
            if paths_changed and self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self.show_toast("Settings saved.", level="success")

    def _maybe_show_first_run(self) -> None:
        if self.settings.first_run_completed:
            return
        dlg = FirstRunDialog(self.settings, self)
        try:
            accepted = dlg.exec()
            result_settings = dlg.result_settings if accepted else None
        finally:
            dlg.deleteLater()
        if accepted and result_settings is not None:
            self.settings = result_settings
            self.settings.save()
            metadata.reset_musicbrainz_useragent()
            metadata.clear_metadata_cache()   # evict stale entries if API key changed
            if self._ripper_view is not None:
                self._ripper_view.apply_settings(self.settings)
            if self._now_playing_view is not None:
                self._now_playing_view._settings = self.settings
            self._apply_video_settings_if_loaded()
            if self._podcast_view is not None:
                self._podcast_view.apply_settings(self.settings)
            if self._radio_view is not None:
                self._radio_view.apply_settings(self.settings)
            self._restart_dlna_server(show_toast=False)
            if self.settings.library_paths:
                self._start_scan(self.settings.library_paths, "Scanned")
            self._restart_library_watcher()
            self.show_toast("Setup saved.", level="success")

    def show_library_stats(self) -> None:
        dlg = LibraryStatsDialog(self.library, parent=self)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def show_diagnostics(self) -> None:
        dlg = DiagnosticsDialog(parent=self)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _restart_dlna_server(self, *, show_toast: bool) -> None:
        self.dlna_server.stop()
        self.dlna_server = DlnaServer(self.library, self.settings)
        if not self.settings.dlna_enabled:
            if show_toast:
                self.show_toast("DLNA sharing stopped.", level="info")
            return
        try:
            self.dlna_server.start()
        except OSError as exc:
            self.statusBar().showMessage(f"DLNA server failed to start: {exc}", 6000)
            if show_toast:
                self.show_toast("DLNA sharing could not start.", level="warning")
            return
        if show_toast:
            detail = f" at {self.dlna_server.base_url}" if self.dlna_server.base_url else ""
            self.show_toast(f"DLNA sharing is running{detail}.", level="success")

    def _confirm_dlna_lan_exposure(self) -> bool:
        result = QMessageBox.question(
            self,
            "Enable DLNA Sharing?",
            (
                "DLNA sharing advertises your indexed audio and video files on the local network "
                "while Sea Lyon is running. Devices on that network may be able to browse and "
                "stream your library without a password.\n\n"
                "Enable DLNA sharing?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return result == QMessageBox.Yes

    def open_queue(self) -> None:
        if self._queue_dialog is None:
            dialog = QueueDialog(self.player, self.library, self)
            dialog.finished.connect(self._clear_queue_dialog)
            dialog.finished.connect(dialog.deleteLater)
            dialog.playlist_saved.connect(self._on_playlist_saved_from_queue)
            self._queue_dialog = dialog
        self._queue_dialog.show()
        self._queue_dialog.raise_()
        self._queue_dialog.activateWindow()

    def _clear_queue_dialog(self, *_args) -> None:
        self._queue_dialog = None

    def _on_playlist_saved_from_queue(self, name: str) -> None:
        self.library_view.refresh_playlists()
        self.show_toast(f'Saved queue as playlist "{name}".', level="success")

    # ------------------------------------------------------------------
    # Cast dialog
    # ------------------------------------------------------------------

    def open_cast_dialog(self) -> None:
        if self._cast_dialog is None:
            dialog = CastDialog(
                on_cast=self._start_cast,
                on_stop=self._stop_cast,
                is_casting=self.cast_controller.is_casting,
                cast_target_name=(
                    self.cast_controller.renderer.friendly_name
                    if self.cast_controller.renderer else ""
                ),
                parent=self,
            )
            dialog.finished.connect(self._clear_cast_dialog)
            dialog.finished.connect(dialog.deleteLater)
            self._cast_dialog = dialog
        self._cast_dialog.show()
        self._cast_dialog.raise_()
        self._cast_dialog.activateWindow()

    def _clear_cast_dialog(self, *_args) -> None:
        self._cast_dialog = None

    def _start_cast(self, renderer) -> None:
        video_track = self._current_video_cast_track()
        if video_track is not None:
            self.cast_controller.start_cast_track(
                renderer,
                video_track,
                self.dlna_server,
                pause_local=self.video_player_view.pause_playback,
            )
            return
        self.cast_controller.start_cast(renderer, self.player, self.dlna_server)

    def _current_video_cast_track(self) -> Track | None:
        if self._video_player_view is None or self.stack.currentWidget() is not self._video_player_view:
            return None
        current_track = getattr(self._video_player_view, "current_library_track", None)
        if not callable(current_track):
            return None
        track = current_track()
        return track if isinstance(track, Track) and track.is_video else None

    def _stop_cast(self) -> None:
        self.cast_controller.stop_cast()

    def _on_cast_started(self, name: str) -> None:
        self.settings.last_cast_renderer = name
        self.settings.save()
        if self._cast_btn is not None:
            self._cast_btn.setProperty("casting", True)
            self._cast_btn.style().unpolish(self._cast_btn)
            self._cast_btn.style().polish(self._cast_btn)
        if self._cast_dialog is not None:
            self._cast_dialog.update_cast_state(True, name)
        self._on_cast_playback_state_changed("playing")
        self.show_toast(f"Casting to {name}.", level="success")

    def _on_cast_stopped(self) -> None:
        if self._cast_btn is not None:
            self._cast_btn.setProperty("casting", False)
            self._cast_btn.style().unpolish(self._cast_btn)
            self._cast_btn.style().polish(self._cast_btn)
        if self._cast_dialog is not None:
            self._cast_dialog.update_cast_state(False)
        self._on_cast_playback_state_changed("stopped")
        self.show_toast("Cast stopped.", level="info")

    def _on_cast_playback_state_changed(self, state: str) -> None:
        self.transport.play_btn.set_playing(state == "playing")

    # ------------------------------------------------------------------

    def _focus_library_search(self) -> None:
        self.tab_bar.setCurrentIndex(self._tab_index["Library"])
        self.library_view.search.setFocus()
        self.library_view.search.selectAll()

    def _jump_to_now_playing(self) -> None:
        track = self.player.current()
        if track is None:
            return
        self.tab_bar.setCurrentIndex(self._tab_index["Library"])
        self.library_view.reveal_track(track)

    def _on_sleep_menu(self, action: QAction) -> None:
        if action is self._sleep_cancel_act:
            self._cancel_sleep_timer()
            return
        seconds = action.data()
        if seconds == -1:  # Custom
            mins, ok = QInputDialog.getInt(self, "Custom Sleep Timer", "Minutes:", 30, 1, 240)
            if not ok:
                return
            seconds = mins * 60
        self._sleep_remaining_s = int(seconds)
        self._sleep_cancel_act.setEnabled(True)
        self._sleep_timer.start()
        self._update_sleep_btn()
        self.show_toast(f"Sleep timer set for {self._sleep_remaining_s // 60} min.", level="info")

    def _on_sleep_tick(self) -> None:
        self._sleep_remaining_s -= 1
        if self._sleep_remaining_s <= 0:
            self._cancel_sleep_timer()
            self.player.stop()
            self.show_toast("Sleep timer: playback stopped.", level="info", duration_ms=4000)
            return
        self._update_sleep_btn()

    def _cancel_sleep_timer(self) -> None:
        self._sleep_timer.stop()
        self._sleep_remaining_s = 0
        self._sleep_cancel_act.setEnabled(False)
        self._update_sleep_btn()

    def _update_sleep_btn(self) -> None:
        if self._sleep_remaining_s > 0:
            mins, secs = divmod(self._sleep_remaining_s, 60)
            self._sleep_btn.setText(f"Sleep {mins}:{secs:02d}")
        else:
            self._sleep_btn.setText("Sleep")

    def show_duplicates(self) -> None:
        dlg = DuplicateDialog(self.library, self)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()
        self.library_view.refresh()

    def open_equalizer(self) -> None:
        if self._equalizer_dialog is None:
            dialog = EqualizerDialog(self.settings, self)
            dialog.equalizer_changed.connect(self.player.set_equalizer)
            dialog.equalizer_changed.connect(self._apply_video_equalizer_if_loaded)
            dialog.settings_saved.connect(self._apply_equalizer_settings)
            dialog.finished.connect(self._clear_equalizer_dialog)
            dialog.finished.connect(dialog.deleteLater)
            self._equalizer_dialog = dialog
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
        self._apply_video_equalizer_if_loaded(self.settings.equalizer_enabled, self.settings.equalizer_bands, self.settings.equalizer_preamp)
        self.show_toast("Equalizer settings saved.", level="success")

    def _clear_equalizer_dialog(self, *_args) -> None:
        self._equalizer_dialog = None

    def show_knowledge_base(self) -> None:
        from .knowledge_base_dialog import KnowledgeBaseDialog
        existing = getattr(self, "_knowledge_base_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dlg = KnowledgeBaseDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda *_: setattr(self, "_knowledge_base_dialog", None))
        self._knowledge_base_dialog = dlg
        dlg.show()

    def show_about(self) -> None:
        dlg = AboutDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.exec()

    def open_log_folder(self) -> None:
        """Help → Open Log Folder. Opens %APPDATA%\\LyonMusicManager\\logs."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = logs_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_toast(
                f"Could not open log folder: {path}",
                level="warning",
            )

    def _maybe_show_smartscreen_advisory(self) -> None:
        """One-time toast explaining the unsigned-installer SmartScreen warning.

        Fires on the first launch of a packaged (PyInstaller-frozen) build
        when the user has not yet seen the advisory. Suppressed in source /
        dev runs since the warning only applies to the installer.
        """
        import sys as _sys

        if not getattr(_sys, "frozen", False):
            return
        if self.settings.smartscreen_advisory_shown:
            return
        self.show_toast(
            "Heads up: Sea Lyon is unsigned for the 1.0 release, so Windows "
            "SmartScreen may have warned you when installing. A signed build "
            "is planned for 1.1 — see the project README for details.",
            level="info",
            duration_ms=10000,
        )
        self.settings.smartscreen_advisory_shown = True
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ auto-update

    _UPDATE_CHECK_INTERVAL_S = 24 * 60 * 60  # at most once per day on startup
    _UPDATE_FAILURE_RETRY_INTERVAL_S = 4 * 60 * 60  # back off outage retries

    def _maybe_check_for_update(self) -> None:
        """Startup hook: check the appcast if the user has opted in.

        - Skipped if first-run is not yet completed (don't spam new users).
        - Skipped if "Check for updates automatically" is unchecked.
        - Skipped if we polled within the last 24 hours.
        """
        if not self.settings.first_run_completed:
            return
        if not self.settings.update_check_enabled:
            return
        import time
        now = time.time()
        elapsed = now - max(0, int(self.settings.last_update_check_ts))
        if elapsed < self._UPDATE_CHECK_INTERVAL_S:
            return
        failure_ts = max(0, int(self.settings.last_update_failure_ts))
        if failure_ts and now - failure_ts < self._UPDATE_FAILURE_RETRY_INTERVAL_S:
            return
        self._start_update_check(manual=False)

    def check_for_updates_now(self) -> None:
        """Help → Check for Updates… entry point. Surfaces a result toast even if up-to-date."""
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        from ..core.updater import UpdateCheckWorker

        if self._update_worker is not None:
            if manual:
                self.show_toast("An update check is already running.", level="info")
            return
        url = self.settings.update_appcast_url
        if not url:
            if manual:
                self.show_toast("No update server is configured.", level="warning")
            return
        thread = QThread()
        worker = UpdateCheckWorker(url, __version__)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(self._on_update_check_finished)
        worker.failed.connect(self._on_update_check_failed)
        worker.finished.connect(self._finish_update_thread)
        worker.failed.connect(self._finish_update_thread)
        self._update_thread = thread
        self._update_worker = worker
        self._update_manual_request = manual
        thread.start()

    def _on_update_check_finished(self, info: object) -> None:
        from ..core.updater import UpdateInfo

        self._update_worker = None
        manual = self._update_manual_request
        self._update_manual_request = False

        import time
        self.settings.last_update_check_ts = int(time.time())
        self.settings.last_update_failure_ts = 0
        # Persist the timestamp without churning the whole save path; settings.save()
        # writes the JSON file atomically.
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001 — must never crash on save failure
            pass

        if info is None or not isinstance(info, UpdateInfo):
            if manual:
                self.show_toast(
                    f"You're running the latest version ({__version__}).",
                    level="success",
                )
            return
        # Don't auto-surface an explicitly skipped version unless this is a manual check.
        if (
            not manual
            and self.settings.skipped_update_version
            and self.settings.skipped_update_version == info.version
        ):
            return
        self._show_update_dialog(info)

    def _on_update_check_failed(self, message: str) -> None:
        self._update_worker = None
        manual = self._update_manual_request
        self._update_manual_request = False
        import time
        self.settings.last_update_failure_ts = int(time.time())
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001 — must never crash on save failure
            pass
        if manual:
            self.show_toast(
                f"Could not check for updates: {message}",
                level="warning",
            )

    def _finish_update_thread(self, *_args: object) -> None:
        thread = self._update_thread
        if thread is None:
            return
        self._update_thread = None
        thread.quit()
        thread.wait(2000)

    def _show_update_dialog(self, info: object) -> None:
        from .update_dialog import UpdateAvailableDialog

        if self._update_dialog is not None and self._update_dialog.isVisible():
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return
        dlg = UpdateAvailableDialog(info, self)  # type: ignore[arg-type]
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.version_skipped.connect(self._on_update_skipped)
        dlg.destroyed.connect(lambda *_: setattr(self, "_update_dialog", None))
        self._update_dialog = dlg
        dlg.show()

    def _on_update_skipped(self, version: str) -> None:
        self.settings.skipped_update_version = version
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ diagnostics actions

    def copy_diagnostics(self) -> None:
        """Help → Copy Diagnostics. Builds a redacted bundle to the clipboard."""
        from PySide6.QtGui import QGuiApplication

        try:
            bundle = collect_diagnostics_bundle()
        except Exception as exc:  # noqa: BLE001 — must never crash the menu
            self.show_toast(
                f"Could not build diagnostics bundle: {exc}",
                level="error",
            )
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self.show_toast("Clipboard is not available.", level="warning")
            return
        clipboard.setText(bundle)
        self.show_toast(
            "Diagnostics copied to clipboard. Paste into a support email.",
            level="success",
            duration_ms=4000,
        )

    # ------------------------------------------------------------------ drag-and-drop
    _DROP_EXTENSIONS = SUPPORTED_EXTS

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
            elif p.suffix.lower() in self._DROP_EXTENSIONS:
                files.append(path)
        if folders:
            for folder in folders:
                if folder not in self.settings.library_paths:
                    self.settings.library_paths.append(folder)
            self.settings.save()
            self._restart_library_watcher()
            self._start_scan(folders, f"Added {len(folders)} folder(s)")
        if files:
            results = [self.library.index_file(f) for f in files]
            self.library.commit()
            added = sum(1 for result in results if result.status == "added")
            updated = sum(1 for result in results if result.status == "updated")
            unchanged = sum(1 for result in results if result.status == "unchanged")
            skipped = sum(1 for result in results if result.status == "skipped")
            failed = sum(1 for result in results if result.status == "failed")
            if added or updated:
                self.dlna_server.invalidate_cache()
                self.library_view.refresh()
                parts: list[str] = []
                if added:
                    plural = "" if added == 1 else "s"
                    parts.append(f"Added {added} file{plural}")
                if updated:
                    parts.append(f"updated {updated}")
                if unchanged:
                    parts.append(f"{unchanged} already in library")
                if skipped:
                    plural = "" if skipped == 1 else "s"
                    parts.append(f"{skipped} file{plural} skipped")
                if failed:
                    plural = "" if failed == 1 else "s"
                    parts.append(f"{failed} file{plural} failed")
                self.show_toast(
                    "; ".join(parts) + ".",
                    level="warning" if failed or skipped else "success",
                )
            else:
                detail_parts: list[str] = []
                if unchanged:
                    detail_parts.append(f"{unchanged} already in library")
                if skipped:
                    plural = "" if skipped == 1 else "s"
                    detail_parts.append(f"{skipped} file{plural} skipped")
                if failed:
                    plural = "" if failed == 1 else "s"
                    detail_parts.append(f"{failed} file{plural} failed")
                detail = " ".join(detail_parts) or f"{len(files)} file(s) skipped."
                if not detail.endswith("."):
                    detail += "."
                self.show_toast(
                    f"No supported files were added. {detail}",
                    level="warning",
                )
        ev.acceptProposedAction()

    def closeEvent(self, ev) -> None:
        self._watch_debounce_timer.stop()
        self._library_watcher.stop()
        if self._watch_index_thread is not None and self._watch_index_thread.isRunning():
            self._watch_index_thread.request_stop()
            if not self._watch_index_thread.wait(3000):
                self.show_toast(
                    "Library update is still stopping. Try closing again in a moment.",
                    level="warning",
                    duration_ms=5000,
                )
                ev.ignore()
                return
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.request_stop()
            if not self._scan_thread.wait(3000):
                self.show_toast(
                    "Library scan is still stopping. Try closing again in a moment.",
                    level="warning",
                    duration_ms=5000,
                )
                ev.ignore()
                return
        if self._rg_scanner is not None and self._rg_scanner.isRunning():
            scanner = self._rg_scanner
            scanner.requestInterruption()
            if not scanner.wait(3000):
                self.show_toast(
                    "ReplayGain scan is still stopping. Try closing again in a moment.",
                    level="warning",
                    duration_ms=5000,
                )
                ev.ignore()
                return
            if self._rg_scanner is scanner:
                scanner.deleteLater()
                self._rg_scanner = None
        if self._podcast_view is not None and not self._podcast_view.shutdown():
            self.show_toast(
                "Podcast refresh is still stopping. Try closing again in a moment.",
                level="warning",
                duration_ms=5000,
            )
            ev.ignore()
            return
        if self._update_thread is not None and self._update_thread.isRunning():
            self._update_thread.quit()
            if not self._update_thread.wait(3000):
                self.show_toast(
                    "Update check is still stopping. Try closing again in a moment.",
                    level="warning",
                    duration_ms=5000,
                )
                ev.ignore()
                return
            self._update_thread = None
            self._update_worker = None
        self.cast_controller.stop_cast()
        self.cast_controller.shutdown()
        self.player.stop()
        self._shutdown_media_key_handler()
        self.dlna_server.stop()
        if self._youtube_view is not None:
            self._youtube_view.shutdown()
        if self._disc_view is not None:
            self._disc_view.shutdown()
        if self._ripper_view is not None:
            self._ripper_view.shutdown()
        self.settings.last_volume = self.player.volume()
        queue = self.player.queue()
        library_queue = [t for t in queue if t.is_library_item]
        self.settings.queue_track_paths = [t.path for t in library_queue]
        current = self.player.current()
        if current is not None and current.is_library_item:
            self.settings.queue_current_index = max(0, self.settings.queue_track_paths.index(current.path))
        else:
            self.settings.queue_current_index = 0
        self.settings.save()
        if self._video_player_view is not None:
            self._video_player_view.cleanup()
        self.player.cleanup()
        self.library.close()
        metadata.shutdown()
        close_cd_dll_handles()
        close_dll_handles()
        super().closeEvent(ev)

    def _shutdown_media_key_handler(self) -> None:
        handler = getattr(self, "_media_key_handler", None)
        self._media_key_handler = None
        close = getattr(handler, "close", None)
        if callable(close):
            close()
