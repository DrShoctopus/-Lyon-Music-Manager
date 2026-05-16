"""Now Playing view + bottom transport bar."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from ..core.library import Track
from ..core.player import Player, RepeatMode
from .transport import (
    NextButton, PlayPauseButton, PrevButton, RepeatButton, ShuffleButton,
    StopButton, VolumeButton,
)
from .widgets import ElidedLabel, cover_pixmap, format_duration, format_ms


_FORMAT_LABELS = ("Codec", "Bitrate", "Sample rate")


class NowPlayingView(QWidget):
    """Now Playing screen: cover, metadata, format strip, and queue preview."""

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player

        self.cover = QLabel()
        self.cover.setFixedSize(360, 360)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#0a0d11;border:1px solid #1c222b;")
        self.cover.setPixmap(cover_pixmap(None, 360, "♪"))

        self.title = QLabel("Nothing playing")
        f = self.title.font(); f.setPointSize(22); f.setBold(True)
        self.title.setFont(f)
        self.title.setObjectName("nowPlayingHeroTitle")
        self.title.setWordWrap(True)

        self.artist = QLabel("")
        f2 = self.artist.font(); f2.setPointSize(13)
        self.artist.setFont(f2)
        self.artist.setObjectName("nowPlayingHeroArtist")

        self.album = QLabel("")
        self.album.setObjectName("mutedText")

        self.format_strip = QLabel("")
        self.format_strip.setObjectName("mutedTextSmall")

        self.position_lbl = QLabel("")
        self.position_lbl.setObjectName("mutedText")

        info = QVBoxLayout()
        info.setSpacing(4)
        info.addStretch(2)
        info.addWidget(self.title)
        info.addWidget(self.artist)
        info.addWidget(self.album)
        info.addSpacing(14)
        info.addWidget(self.format_strip)
        info.addWidget(self.position_lbl)
        info.addStretch(3)

        info_w = QWidget()
        info_w.setLayout(info)
        info_w.setMinimumWidth(280)

        # Up Next queue preview
        queue_header = QLabel("Up Next")
        queue_header.setObjectName("sectionHeading")
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queuePreview")
        self.queue_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.queue_list.setUniformItemSizes(True)
        self.queue_list.itemDoubleClicked.connect(self._on_queue_double_clicked)

        queue_box = QVBoxLayout()
        queue_box.setSpacing(4)
        queue_box.addWidget(queue_header)
        queue_box.addWidget(self.queue_list, 1)
        queue_w = QWidget()
        queue_w.setLayout(queue_box)
        queue_w.setMinimumWidth(220)
        queue_w.setMaximumWidth(340)

        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(self.cover, 0, Qt.AlignTop)
        row.addWidget(info_w, 1)
        row.addWidget(queue_w, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addLayout(row, 1)

        player.track_changed.connect(self._on_track)
        player.queue_changed.connect(self._refresh_queue)
        player.position_changed.connect(self._on_position)
        self._refresh_queue()

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title.setText("Nothing playing")
            self.artist.setText("")
            self.album.setText("")
            self.format_strip.setText("")
            self.position_lbl.setText("")
            self.cover.setPixmap(cover_pixmap(None, 360, "♪"))
        else:
            self.title.setText(track.title or "Untitled")
            self.artist.setText(track.display_artist)
            self.album.setText(track.album or "")
            self.format_strip.setText(self._format_strip_text(track))
            self.cover.setPixmap(cover_pixmap(track.artwork_path, 360, "♪"))
        self._refresh_queue()

    def _on_position(self, pos_ms: int, dur_ms: int) -> None:
        if dur_ms <= 0 and pos_ms <= 0:
            self.position_lbl.setText("")
            return
        self.position_lbl.setText(f"{format_ms(pos_ms)} / {format_ms(dur_ms)}")

    @staticmethod
    def _format_strip_text(track: Track) -> str:
        from pathlib import Path
        bits: list[str] = []
        ext = Path(track.path).suffix.lstrip(".").upper()
        if ext:
            bits.append(ext)
        if getattr(track, "bitrate", 0):
            kbps = round(track.bitrate / 1000)
            if kbps > 0:
                bits.append(f"{kbps} kbps")
        if getattr(track, "samplerate", 0):
            sr = track.samplerate
            bits.append(f"{sr // 1000} kHz" if sr % 1000 == 0 else f"{sr / 1000:g} kHz")
        return "  ·  ".join(bits)

    def _refresh_queue(self) -> None:
        self.queue_list.clear()
        queue = self.player.queue()
        current = self.player.current_index()
        upcoming = queue[current + 1:current + 1 + 12] if current >= 0 else queue[:12]
        if not upcoming:
            placeholder = QListWidgetItem("Queue is empty.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.queue_list.addItem(placeholder)
            return
        base = current + 1 if current >= 0 else 0
        for offset, track in enumerate(upcoming):
            item = QListWidgetItem(f"{track.title}  —  {track.display_artist}")
            item.setData(Qt.UserRole, base + offset)
            self.queue_list.addItem(item)

    def _on_queue_double_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.UserRole)
        if isinstance(idx, int):
            self.player.play_index(idx)


class TransportBar(QWidget):
    """Persistent bottom transport bar."""

    open_now_playing = Signal()
    play_requested = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player
        self._user_dragging = False

        self.bar = QFrame(self)
        self.bar.setObjectName("transport")

        self.thumb = QLabel()
        self.thumb.setObjectName("transportThumb")
        self.thumb.setFixedSize(68, 68)
        self.thumb.setPixmap(cover_pixmap(None, 68, "♪"))
        self.thumb.setCursor(Qt.PointingHandCursor)
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
        meta_w.setMaximumWidth(340)
        meta_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        self.shuffle_btn = ShuffleButton()
        self.repeat_btn = RepeatButton()
        self.stop_btn = StopButton()
        self.prev_btn = PrevButton()
        self.next_btn = NextButton()
        self.play_btn = PlayPauseButton()
        self.vol_btn = VolumeButton()
        self.vol_btn.set_state(player.volume(), player.is_muted())

        self.play_btn.clicked.connect(self.play_requested.emit)
        self.prev_btn.clicked.connect(player.previous)
        self.next_btn.clicked.connect(player.next)
        self.stop_btn.clicked.connect(player.stop)
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
        center.setSpacing(2)
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
        bar_layout.setContentsMargins(18, 8, 18, 8)
        bar_layout.setSpacing(12)
        bar_layout.addWidget(self.thumb)
        bar_layout.addWidget(meta_w)
        bar_layout.addStretch(1)
        bar_layout.addWidget(center_w, 3)
        bar_layout.addStretch(1)
        bar_layout.addLayout(vol_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.bar)

        player.track_changed.connect(self._on_track)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)

    @staticmethod
    def _repeat_to_int(mode: RepeatMode) -> int:
        return {RepeatMode.OFF: 0, RepeatMode.ALL: 1, RepeatMode.ONE: 2}[mode]

    def _on_repeat_clicked(self, _state: int) -> None:
        # The user already cycled the visible state; advance the player to match.
        mode = self.player.cycle_repeat()
        self.repeat_btn.set_state(self._repeat_to_int(mode))

    def _on_volume_slider(self, value: int) -> None:
        self.player.set_volume(value)
        self.vol_btn.set_state(value, self.player.is_muted())

    def _on_track(self, track: Track | None) -> None:
        if track is None:
            self.title_lbl.setText("Nothing playing")
            self.artist_lbl.setText("")
            self.thumb.setPixmap(cover_pixmap(None, 68, "♪"))
        else:
            self.title_lbl.setText(track.title)
            self.artist_lbl.setText(f"{track.display_artist} - {track.album}")
            self.thumb.setPixmap(cover_pixmap(track.artwork_path, 68, "♪"))

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

    def _on_state(self, state: str) -> None:
        self.play_btn.set_playing(state == "playing")
        self.vol_btn.set_state(self.vol.value(), self.player.is_muted())

    def _on_seek_release(self) -> None:
        self.player.seek(self.seek.value())
        self._user_dragging = False
