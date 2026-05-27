"""Persistent bottom transport bar (extracted from now_playing.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from ..core.library import Library, Track
from ..core.player import Player, RepeatMode
from .transport import (
    HeartButton, NextButton, PlayPauseButton, PrevButton, RepeatButton,
    ShuffleButton, StopButton, VolumeButton,
)
from .widgets import ElidedLabel, cover_pixmap, format_ms

_TRANSPORT_THUMB_SIZE = 60


# ---- Clickable QLabel --------------------------------------------------

class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)


# ---- TransportBar -------------------------------------------------------

class TransportBar(QWidget):
    """Persistent bottom transport bar."""

    open_now_playing = Signal()
    play_requested = Signal()
    previous_requested = Signal()
    next_requested = Signal()
    stop_requested = Signal()

    def __init__(
        self,
        player: Player,
        library: Library | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.player = player
        self._library = library
        self._user_dragging = False

        self.bar = QFrame(self)
        self.bar.setObjectName("transport")

        self.thumb = _ClickableLabel()
        self.thumb.setObjectName("transportThumb")
        self.thumb.setFixedSize(_TRANSPORT_THUMB_SIZE, _TRANSPORT_THUMB_SIZE)
        self.thumb.setPixmap(cover_pixmap(None, _TRANSPORT_THUMB_SIZE, "♪"))
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setAccessibleName("Open Now Playing")
        self.thumb.clicked.connect(self.open_now_playing.emit)

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
        meta_w.setMaximumWidth(340)
        meta_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self.heart_btn = HeartButton()
        self.heart_btn.setEnabled(False)
        self.heart_btn.toggled.connect(self._on_heart_toggled)

        self.shuffle_btn = ShuffleButton()
        self.repeat_btn = RepeatButton()
        self.stop_btn = StopButton()
        self.prev_btn = PrevButton()
        self.next_btn = NextButton()
        self.play_btn = PlayPauseButton()
        self.vol_btn = VolumeButton()
        self.vol_btn.set_state(player.volume(), player.is_muted())

        self.play_btn.clicked.connect(self.play_requested.emit)
        self.prev_btn.clicked.connect(self.previous_requested.emit)
        self.next_btn.clicked.connect(self.next_requested.emit)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.shuffle_btn.toggled.connect(player.set_shuffle)
        self.shuffle_btn.setChecked(player.shuffle())
        self.repeat_btn.set_state(self._repeat_to_int(player.repeat()))
        self.repeat_btn.state_changed.connect(self._on_repeat_clicked)
        self.vol_btn.toggled.connect(self._on_mute_toggled)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        controls.addWidget(self.stop_btn)
        controls.addSpacing(6)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.setAlignment(Qt.AlignCenter)

        self.elapsed_lbl = QLabel("0:00")
        self.elapsed_lbl.setObjectName("timeLabel")
        self.elapsed_lbl.setMinimumWidth(42)
        self.elapsed_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.total_lbl = QLabel("0:00")
        self.total_lbl.setObjectName("timeLabel")
        self.total_lbl.setMinimumWidth(42)
        self.total_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setAccessibleName("Seek position")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.seek.sliderReleased.connect(self._on_seek_release)

        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(6)
        seek_row.addWidget(self.elapsed_lbl)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.total_lbl)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(14)
        center.addLayout(controls)
        center.addLayout(seek_row)

        center_w = QWidget()
        center_w.setLayout(center)
        center_w.setMinimumWidth(330)
        center_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(player.volume())
        self.vol.setObjectName("volumeSlider")
        self.vol.setMinimumWidth(100)
        self.vol.setMaximumWidth(150)
        self.vol.setAccessibleName("Volume")
        self.vol.valueChanged.connect(self._on_volume_slider)

        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(4)
        vol_row.addWidget(self.vol_btn)
        vol_row.addWidget(self.vol)

        bar_layout = QHBoxLayout(self.bar)
        bar_layout.setContentsMargins(14, 6, 14, 6)
        bar_layout.setSpacing(12)
        bar_layout.addWidget(self.thumb)
        bar_layout.addWidget(meta_w)
        bar_layout.addWidget(self.heart_btn)
        bar_layout.addStretch(1)
        bar_layout.addWidget(center_w, 3)
        bar_layout.addStretch(1)
        bar_layout.addLayout(vol_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.bar)

        player.track_changed.connect(self._on_track)
        if hasattr(player, "stream_metadata_changed"):
            player.stream_metadata_changed.connect(self._on_track)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)

    @staticmethod
    def _repeat_to_int(mode: RepeatMode) -> int:
        return {RepeatMode.OFF: 0, RepeatMode.ALL: 1, RepeatMode.ONE: 2}[mode]

    def _on_repeat_clicked(self, _state: int) -> None:
        mode = self.player.cycle_repeat()
        self.repeat_btn.set_state(self._repeat_to_int(mode))

    def _on_volume_slider(self, value: int) -> None:
        self.player.set_volume(value)
        self.vol_btn.set_state(value, self.player.is_muted())

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title_lbl.setText("Nothing playing")
            self.artist_lbl.setText("")
            self.thumb.setPixmap(cover_pixmap(None, _TRANSPORT_THUMB_SIZE, "♪"))
            self.heart_btn.blockSignals(True)
            self.heart_btn.setChecked(False)
            self.heart_btn.blockSignals(False)
            self.heart_btn.setEnabled(False)
        else:
            self.title_lbl.setText(track.title)
            parts = [p for p in (track.display_artist, track.album) if p]
            self.artist_lbl.setText(" - ".join(parts))
            self.thumb.setPixmap(cover_pixmap(track.artwork_path, _TRANSPORT_THUMB_SIZE, "♪"))
            self.heart_btn.blockSignals(True)
            self.heart_btn.setChecked(track.liked)
            self.heart_btn.blockSignals(False)
            self.heart_btn.setEnabled(self._library is not None and track.is_library_item)

    def _on_position(self, pos_ms: int, dur_ms: int) -> None:
        if not self._user_dragging:
            self.seek.blockSignals(True)
            self.seek.setRange(0, max(0, dur_ms))
            self.seek.setValue(pos_ms)
            self.seek.blockSignals(False)
        self.elapsed_lbl.setText(format_ms(pos_ms))
        self.total_lbl.setText(format_ms(dur_ms))

    def _on_mute_toggled(self, muted: bool) -> None:
        self.player.set_muted(muted)
        self.vol_btn.set_state(self.vol.value(), muted)

    def _on_heart_toggled(self, liked: bool) -> None:
        track = self.player.current()
        if track is not None and track.is_library_item and self._library is not None:
            track.liked = liked
            self._library.update_liked(track.id, liked)

    def _on_state(self, state: str) -> None:
        self.play_btn.set_playing(state == "playing")
        self.vol_btn.set_state(self.vol.value(), self.player.is_muted())

    def _on_seek_release(self) -> None:
        self.player.seek(self.seek.value())
        self._user_dragging = False
