"""Top-level window with WMP-style title, tab bar, stacked views."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.library import Library
from ..core.player import Player
from ..core.settings import Settings
from .library_view import LibraryView
from .now_playing import NowPlayingView, TransportBar
from .ripper_view import RipperView
from .styles import WMP_QSS


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self)
        self.player.set_volume(self.settings.last_volume)

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
        for name in ("Now Playing", "Library", "Rip"):
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
        layout.addWidget(tabs)

        # ---- stacked content
        self.stack = QStackedWidget()
        self.now_playing = NowPlayingView(self.player)
        self.library_view = LibraryView(self.library)
        self.ripper_view = RipperView(self.settings, self.library)

        self.stack.addWidget(self.now_playing)
        self.stack.addWidget(self.library_view)
        self.stack.addWidget(self.ripper_view)

        self._tab_buttons["Now Playing"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.now_playing))
        self._tab_buttons["Library"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.library_view))
        self._tab_buttons["Rip"].toggled.connect(
            lambda c: c and self.stack.setCurrentWidget(self.ripper_view))
        self._tab_buttons["Library"].setChecked(True)

        layout.addWidget(self.stack, 1)

        # ---- transport bar
        self.transport = TransportBar(self.player)
        self.transport.open_now_playing.connect(
            lambda: self._tab_buttons["Now Playing"].setChecked(True))
        layout.addWidget(self.transport)

        self.setCentralWidget(root)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(f"{__app_name__} {__version__} - ready")

        # Wire library actions
        self.library_view.play_tracks.connect(self.player.set_queue)
        self.library_view.enqueue_tracks.connect(self.player.enqueue)
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_rescan.connect(self.rescan)
        self.ripper_view.rip_completed.connect(self.library_view.refresh)
        self.ripper_view.log.connect(lambda m: sb.showMessage(m, 4000))

        # Initial scan of saved roots, async-ish
        if self.settings.library_paths:
            self.statusBar().showMessage("Scanning library...")
            n = self.library.scan_paths(self.settings.library_paths)
            self.statusBar().showMessage(f"Scanned: {n} new tracks", 4000)
            self.library_view.refresh()

        # Menu
        self._build_menu()

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

        help_menu = m.addMenu("&Help")
        help_menu.addAction(QAction("About", self, triggered=self.show_about))

    # ------------------------------------------------------------------ actions
    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add music folder")
        if not folder:
            return
        if folder not in self.settings.library_paths:
            self.settings.library_paths.append(folder)
            self.settings.save()
        self.statusBar().showMessage(f"Scanning {folder}...")
        n = self.library.scan_paths([folder])
        self.statusBar().showMessage(f"Added {n} tracks from {folder}", 5000)
        self.library_view.refresh()

    def rescan(self) -> None:
        self.statusBar().showMessage("Rescanning library...")
        n = self.library.scan_paths(self.settings.library_paths or [self.settings.music_root])
        self.statusBar().showMessage(f"Rescanned: {n} new tracks", 5000)
        self.library_view.refresh()

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
            self.statusBar().showMessage("Settings saved.", 3000)

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About " + __app_name__,
            f"<h3>{__app_name__} {__version__}</h3>"
            "<p>Rip your CDs to FLAC, manage your library, and play music "
            "with a familiar Windows Media Player look.</p>"
            "<p>Uses MusicBrainz, Cover Art Archive, and ffmpeg.</p>",
        )

    def closeEvent(self, ev) -> None:
        self.settings.last_volume = self.player.volume()
        self.settings.save()
        super().closeEvent(ev)
