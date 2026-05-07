"""Spotify-style main window: left sidebar + stacked content + bottom transport."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QMainWindow, QMessageBox,
    QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from .. import __app_name__, __version__
from ..core.library import Library
from ..core.player import Player
from ..core.settings import Settings
from .home_view import HomeView
from .library_view import LibraryView
from .now_playing import NowPlayingView, TransportBar
from .ripper_view import RipperView
from .sidebar import Sidebar
from .styles import SPOTIFY_QSS
from .youtube_view import YouTubeView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library()
        self.player = Player(self)
        self.player.set_volume(self.settings.last_volume)

        self.setWindowTitle(__app_name__)
        self.resize(1200, 780)
        self.setMinimumSize(960, 620)
        self.setStyleSheet(SPOTIFY_QSS)

        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Top: sidebar + content
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)

        self.sidebar = Sidebar()
        top.addWidget(self.sidebar)

        # Content frame holds the stack
        content_frame = QFrame()
        content_frame.setObjectName("content")
        cf_layout = QVBoxLayout(content_frame)
        cf_layout.setContentsMargins(0, 0, 0, 0)
        cf_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.home_view = HomeView(self.library)
        self.library_view = LibraryView(self.library)
        self.youtube_view = YouTubeView()
        self.ripper_view = RipperView(self.settings, self.library)
        self.now_playing_view = NowPlayingView(self.player)

        for w in (self.home_view, self.library_view, self.youtube_view,
                  self.ripper_view, self.now_playing_view):
            self.stack.addWidget(w)

        cf_layout.addWidget(self.stack, 1)
        top.addWidget(content_frame, 1)

        outer.addLayout(top, 1)

        # Bottom transport bar spans full width
        self.transport = TransportBar(self.player)
        self.transport.open_now_playing.connect(self._show_now_playing)
        outer.addWidget(self.transport)

        self.setCentralWidget(root)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(f"{__app_name__} {__version__} - ready")

        # Wire navigation
        self.sidebar.nav_changed.connect(self._on_nav)
        self.sidebar.set_active("home")

        # Wire actions
        self.home_view.open_album.connect(self._open_album)
        self.home_view.open_library.connect(lambda: self.sidebar.set_active("library"))
        self.home_view.open_rip.connect(lambda: self.sidebar.set_active("rip"))
        self.library_view.play_tracks.connect(self.player.set_queue)
        self.library_view.enqueue_tracks.connect(self.player.enqueue)
        self.library_view.request_add_folder.connect(self.add_folder)
        self.library_view.request_rescan.connect(self.rescan)
        self.ripper_view.rip_completed.connect(self._after_rip)
        self.ripper_view.log.connect(lambda m: sb.showMessage(m, 4000))

        # Initial scan
        if self.settings.library_paths:
            self.statusBar().showMessage("Scanning library...")
            n = self.library.scan_paths(self.settings.library_paths)
            self.statusBar().showMessage(f"Scanned: {n} new tracks", 4000)
            self.library_view.refresh()
            self.home_view.refresh()

        self._build_menu()

    # ------------------------------------------------------------------ navigation
    def _on_nav(self, key: str) -> None:
        mapping = {
            "home": self.home_view,
            "library": self.library_view,
            "youtube": self.youtube_view,
            "rip": self.ripper_view,
        }
        target = mapping.get(key)
        if target:
            self.stack.setCurrentWidget(target)

    def _show_now_playing(self) -> None:
        self.stack.setCurrentWidget(self.now_playing_view)
        # No sidebar entry checked; close-out happens when user picks one again
        for k in ("home", "library", "youtube", "rip"):
            btn = self.sidebar.button(k)
            if btn and btn.isChecked():
                btn.setChecked(False)

    def _open_album(self, artist: str, album: str) -> None:
        # Switch to library tab and select the album
        self.sidebar.set_active("library")
        self.library_view.select_album(artist, album)

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
        file_menu.addAction(QAction("Settings...", self, triggered=self.open_settings))
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
        self.home_view.refresh()

    def rescan(self) -> None:
        self.statusBar().showMessage("Rescanning library...")
        n = self.library.scan_paths(self.settings.library_paths or [self.settings.music_root])
        self.statusBar().showMessage(f"Rescanned: {n} new tracks", 5000)
        self.library_view.refresh()
        self.home_view.refresh()

    def remove_missing(self) -> None:
        n = self.library.remove_missing()
        self.statusBar().showMessage(f"Removed {n} missing tracks", 5000)
        self.library_view.refresh()
        self.home_view.refresh()

    def _after_rip(self) -> None:
        self.library_view.refresh()
        self.home_view.refresh()

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
            "<p>Rip your CDs to FLAC, manage your library, browse YouTube, "
            "and play music with a Spotify-inspired interface.</p>"
            "<p>Uses MusicBrainz, Cover Art Archive, ffmpeg, and Qt WebEngine.</p>",
        )

    def closeEvent(self, ev) -> None:
        self.settings.last_volume = self.player.volume()
        self.settings.save()
        super().closeEvent(ev)
