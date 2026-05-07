"""Now Playing view + bottom transport bar."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSizePolicy,
    QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..core.library import Track
from ..core.player import Player, RepeatMode
from .widgets import ElidedLabel, cover_pixmap, format_ms


class NowPlayingView(QWidget):
    """Big-cover now-playing screen with the upcoming queue."""

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player

        self.cover = QLabel()
        self.cover.setFixedSize(360, 360)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#0a0d11;border:1px solid #1c222b;")
        self.cover.setPixmap(cover_pixmap(None, 360, "♪"))

        self.title = QLabel("Nothing playing")
        f = self.title.font(); f.setPointSize(20); f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet("color:#ffb24d;")
        self.artist = QLabel("")
        f2 = self.artist.font(); f2.setPointSize(12)
        self.artist.setFont(f2)
        self.album = QLabel("")
        self.album.setStyleSheet("color:#aab3c0;")

        info = QVBoxLayout()
        info.addStretch(1)
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addWidget(self.album)
        info.addStretch(1)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.cover)
        top.addSpacing(20)
        top.addLayout(info, 1)
        top.addStretch(1)

        # Up-next queue
        queue_label = QLabel("Up Next")
        queue_label.setStyleSheet("color:#ffb24d;font-weight:600;padding:4px 6px;")
        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self._on_queue_double)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addLayout(top, 3)
        layout.addWidget(queue_label)
        layout.addWidget(self.queue_list, 2)

        player.track_changed.connect(self._on_track)
        player.queue_changed.connect(self._refresh_queue)

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title.setText("Nothing playing")
            self.artist.setText("")
            self.album.setText("")
            self.cover.setPixmap(cover_pixmap(None, 360, "♪"))
        else:
            self.title.setText(track.title)
            self.artist.setText(track.display_artist)
            self.album.setText(track.album)
            self.cover.setPixmap(cover_pixmap(track.artwork_path, 360, "♪"))
        self._refresh_queue()

    def _refresh_queue(self) -> None:
        self.queue_list.clear()
        current = self.player.current()
        for t in self.player.queue():
            label = f"{t.title}  -  {t.display_artist}"
            it = QListWidgetItem(label)
            if current and t.path == current.path:
                f = it.font(); f.setBold(True); it.setFont(f)
                it.setForeground(Qt.GlobalColor.yellow)
            self.queue_list.addItem(it)

    def _on_queue_double(self, item: QListWidgetItem) -> None:
        row = self.queue_list.row(item)
        self.player.play_index(row)


class TransportBar(QFrame):
    """The fixed bottom playback bar (WMP-style)."""

    open_now_playing = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player
        self.setObjectName("transport")
        self._user_dragging = False

        # Cover thumb
        self.thumb = QLabel()
        self.thumb.setFixedSize(56, 56)
        self.thumb.setPixmap(cover_pixmap(None, 56, "♪"))
        self.thumb.setStyleSheet("border:1px solid #000;")
        self.thumb.mousePressEvent = lambda ev: self.open_now_playing.emit()

        self.title_lbl = ElidedLabel("Nothing playing")
        self.title_lbl.setObjectName("nowPlayingTitle")
        self.artist_lbl = ElidedLabel("")
        self.artist_lbl.setObjectName("nowPlayingArtist")

        meta = QVBoxLayout()
        meta.setSpacing(0)
        meta.addStretch(1)
        meta.addWidget(self.title_lbl)
        meta.addWidget(self.artist_lbl)
        meta.addStretch(1)

        meta_w = QWidget()
        meta_w.setLayout(meta)
        meta_w.setMinimumWidth(180)
        meta_w.setMaximumWidth(280)
        meta_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Transport buttons
        self.prev_btn = self._make_btn("⏮")
        self.play_btn = self._make_btn("▶", primary=True)
        self.next_btn = self._make_btn("⏭")
        self.stop_btn = self._make_btn("■")
        self.shuffle_btn = self._make_btn("⤮")
        self.shuffle_btn.setCheckable(True)
        self.repeat_btn = self._make_btn("⟳")
        self.repeat_btn.setCheckable(True)

        self.prev_btn.clicked.connect(player.previous)
        self.next_btn.clicked.connect(player.next)
        self.stop_btn.clicked.connect(player.stop)
        self.play_btn.clicked.connect(player.toggle)
        self.shuffle_btn.toggled.connect(player.set_shuffle)
        self.repeat_btn.clicked.connect(self._cycle_repeat)

        controls = QHBoxLayout()
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.repeat_btn)

        # Seek
        self.elapsed_lbl = QLabel("0:00")
        self.elapsed_lbl.setObjectName("timeLabel")
        self.total_lbl = QLabel("0:00")
        self.total_lbl.setObjectName("timeLabel")
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.seek.sliderReleased.connect(self._on_seek_release)

        seek_row = QHBoxLayout()
        seek_row.addWidget(self.elapsed_lbl)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.total_lbl)

        center = QVBoxLayout()
        center.setContentsMargins(0, 6, 0, 6)
        center.addLayout(controls)
        center.addLayout(seek_row)

        # Volume
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(player.volume())
        self.vol.setMaximumWidth(120)
        self.vol.valueChanged.connect(player.set_volume)
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("🔊"))
        vol_row.addWidget(self.vol)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.addWidget(self.thumb)
        outer.addWidget(meta_w)
        outer.addLayout(center, 1)
        outer.addLayout(vol_row)

        player.track_changed.connect(self._on_track)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)

    def _make_btn(self, text: str, primary: bool = False) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setObjectName("transportPlay" if primary else "transportBtn")
        return b

    def _cycle_repeat(self) -> None:
        mode = self.player.cycle_repeat()
        self.repeat_btn.setChecked(mode != RepeatMode.OFF)
        labels = {RepeatMode.OFF: "⟳", RepeatMode.ALL: "⟳A", RepeatMode.ONE: "⟳1"}
        self.repeat_btn.setText(labels[mode])

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title_lbl.setText("Nothing playing")
            self.artist_lbl.setText("")
            self.thumb.setPixmap(cover_pixmap(None, 56, "♪"))
        else:
            self.title_lbl.setText(track.title)
            self.artist_lbl.setText(f"{track.display_artist} - {track.album}")
            self.thumb.setPixmap(cover_pixmap(track.artwork_path, 56, "♪"))

    def _on_position(self, pos_ms: int, dur_ms: int) -> None:
        if not self._user_dragging:
            self.seek.blockSignals(True)
            self.seek.setRange(0, max(0, dur_ms))
            self.seek.setValue(pos_ms)
            self.seek.blockSignals(False)
        self.elapsed_lbl.setText(format_ms(pos_ms))
        self.total_lbl.setText(format_ms(dur_ms))

    def _on_state(self, state: str) -> None:
        self.play_btn.setText("❚❚" if state == "playing" else "▶")

    def _on_seek_release(self) -> None:
        self.player.seek(self.seek.value())
        self._user_dragging = False
