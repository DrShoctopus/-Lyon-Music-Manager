"""Top-level window with WMP-style title, tab bar, stacked views."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.library import Library
from ..core.player import Player
from ..core.settings import Settings
from .equalizer_dialog import EqualizerDialog
from .library_view import LibraryView
from .now_playing import NowPlayingView, TransportBar
from .ripper_view import RipperView
from .setup_dialog import SetupDialog
from .styles import WMP_QSS
from .youtube_view import YouTubeView


@dataclass(frozen=True)
class _TabSpec:
    """Declarative metadata for the main navigation tabs."""

    label: str
    view_attr: str


NAV_TABS = (
    _TabSpec("Now Playing", "now_playing"),
    _TabSpec("Library", "library_view"),
    _TabSpec("Rip", "ripper_view"),
    _TabSpec("YouTube", "youtube_view"),
)


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
        self._init_services()
        self._configure_window()

        root, layout = self._build_root_container()
        layout.addWidget(self._build_title_bar())
        layout.addWidget(self._build_tab_bar())
        self._build_views()
        layout.addWidget(self.stack, 1)
        self._build_transport_bar(layout)
        self.setCentralWidget(root)

        self._build_status_bar()
        self._connect_library_actions()
        self._build_menu()
        self._start_initial_scan()
        QTimer.singleShot(500, self._show_first_run_setup)

    # ------------------------------------------------------------------ setup
    def _init_services(self) -> None:
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self)
        self.player.set_volume(self.settings.last_volume)
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)
        self._scan_thread: _LibraryScanThread | None = None
        self._equalizer_dialog: EqualizerDialog | None = None
        self._setup_dialog: SetupDialog | None = None

    def _configure_window(self) -> None:
        self.setWindowTitle(__app_name__)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(WMP_QSS)

    def _build_root_container(self) -> tuple[QWidget, QVBoxLayout]:
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return root, layout

    def _build_title_bar(self) -> QFrame:
        title = QFrame()
        title.setObjectName("titlebar")
        layout = QHBoxLayout(title)
        layout.setContentsMargins(12, 0, 12, 0)

        title_label = QLabel(__app_name__)
        title_label.setObjectName("titleLabel")
        layout.addWidget(title_label)
        layout.addStretch(1)
        return title

    def _build_tab_bar(self) -> QFrame:
        tabs = QFrame()
        tabs.setObjectName("tabbar")
        layout = QHBoxLayout(tabs)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self._tab_buttons: dict[str, QPushButton] = {}

        for tab in NAV_TABS:
            button = self._create_nav_button(tab.label)
            layout.addWidget(button)
            self.tab_group.addButton(button)
            self._tab_buttons[tab.label] = button

        layout.addStretch(1)
        layout.addWidget(self._create_command_button("Settings", self.open_settings))
        layout.addWidget(self._create_command_button("6 Band EQ", self.open_equalizer))
        return tabs

    def _create_nav_button(self, label: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("navTab")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _create_command_button(self, label: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("navTab")
        button.clicked.connect(handler)
        return button

    def _build_views(self) -> None:
        self.stack = QStackedWidget()
        self.now_playing = NowPlayingView(self.player)
        self.library_view = LibraryView(self.library)
        self.ripper_view = RipperView(self.settings, self.library)
        self.youtube_view = YouTubeView()

        for tab in NAV_TABS:
            view = getattr(self, tab.view_attr)
            self.stack.addWidget(view)
            self._tab_buttons[tab.label].toggled.connect(
                lambda checked, current_view=view: (
                    checked and self.stack.setCurrentWidget(current_view)
                )
            )

        self._select_tab("Library")
        self.stack.currentChanged.connect(self._on_view_changed)

    def _build_transport_bar(self, layout: QVBoxLayout) -> None:
        self.transport = TransportBar(self.player)
        self.transport.open_now_playing.connect(lambda: self._select_tab("Now Playing"))
        layout.addWidget(self.transport)

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage(f"{__app_name__} {__version__} - ready")

    def _connect_library_actions(self) -> None:
        status_bar = self.statusBar()
        self.library_view.play_tracks.connect(self.player.set_queue)
        self.library_view.enqueue_tracks.connect(self._enqueue_tracks)
        self.library_view.status_message.connect(
            lambda message: status_bar.showMessage(message, 3000)
        )
        self.player.track_changed.connect(self.library_view.highlight_track)
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_rescan.connect(self.rescan)
        self.ripper_view.rip_completed.connect(self.library_view.refresh)
        self.ripper_view.log.connect(lambda message: status_bar.showMessage(message, 4000))

    def _start_initial_scan(self) -> None:
        if self.settings.library_paths:
            self._start_scan(self.settings.library_paths, "Scanned")

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        self._add_action(file_menu, "Add Folder to Library...", self.add_folder)
        self._add_action(file_menu, "Rescan Library", self.rescan)
        self._add_action(file_menu, "Remove Missing Files", self.remove_missing)
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close)

        help_menu = menu_bar.addMenu("&Help")
        self._add_action(help_menu, "Setup && Health Check", self.show_setup_health)
        self._add_action(help_menu, "About", self.show_about)

    def _add_action(self, menu: QMenu, label: str, handler: Callable[[], None]) -> None:
        menu.addAction(QAction(label, self, triggered=handler))

    # ------------------------------------------------------------------ tabs
    def _select_tab(self, label: str) -> None:
        self._tab_buttons[label].setChecked(True)

    def _on_view_changed(self, _idx: int) -> None:
        current = self.stack.currentWidget()
        is_youtube = current is self.youtube_view
        is_rip = current is self.ripper_view
        hide_transport = is_youtube or is_rip
        self.transport.setVisible(not hide_transport)
        if hide_transport:
            self.player.stop()
        if not is_youtube:
            self.youtube_view.pause_all_videos()

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
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.result_settings
            self.settings.save()
            self.ripper_view.apply_settings(self.settings)
            if self._setup_dialog is not None:
                self._setup_dialog.settings = self.settings
                self._setup_dialog.refresh()
            self.player.set_equalizer(
                self.settings.equalizer_enabled, self.settings.equalizer_bands
            )
            self.statusBar().showMessage("Settings saved.", 3000)

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
        self.player.set_equalizer(self.settings.equalizer_enabled, self.settings.equalizer_bands)
        self.statusBar().showMessage("Equalizer settings saved.", 3000)

    def _clear_equalizer_dialog(self, *_args) -> None:
        self._equalizer_dialog = None


    def _show_first_run_setup(self) -> None:
        if not self.settings.setup_completed:
            self.show_setup_health(mark_complete_on_close=True)

    def show_setup_health(self, *, mark_complete_on_close: bool = False) -> None:
        if self._setup_dialog is not None:
            self._setup_dialog.raise_()
            self._setup_dialog.activateWindow()
            return
        dlg = SetupDialog(self.settings, self)
        self._setup_dialog = dlg
        dlg.open_settings_requested.connect(self.open_settings)
        dlg.finished.connect(lambda *_: self._clear_setup_dialog(mark_complete_on_close))
        dlg.show()

    def _clear_setup_dialog(self, mark_complete: bool) -> None:
        self._setup_dialog = None
        if mark_complete and not self.settings.setup_completed:
            self.settings.setup_completed = True
            self.settings.save()

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
