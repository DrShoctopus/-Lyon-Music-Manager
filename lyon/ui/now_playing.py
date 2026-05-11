"""Now Playing view + bottom transport bar."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..core.library import Track
from ..core.player import Player, RepeatMode
from .widgets import ElidedLabel, cover_pixmap, format_ms


class NowPlayingView(QWidget):
    """Big-cover now-playing screen."""

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
        self.title.setStyleSheet("color:#72f4ff;")
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addStretch(1)
        layout.addLayout(top)
        layout.addSpacing(16)
        layout.addWidget(self._build_queue_panel())
        layout.addStretch(1)

        player.track_changed.connect(self._on_track)
        player.queue_changed.connect(self._refresh_queue)
        self._refresh_queue()


    def _build_queue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("queuePanel")
        panel.setMinimumHeight(190)

        title = QLabel("Up Next")
        title.setStyleSheet("color:#72f4ff;font-weight:600;padding:4px 0;")
        self.queue_list = QListWidget()
        self.queue_list.setAlternatingRowColors(True)
        self.queue_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.queue_list.itemDoubleClicked.connect(self._play_queue_item)
        self.queue_list.itemSelectionChanged.connect(self._update_queue_buttons)

        self.queue_play_btn = QPushButton("Play Selected")
        self.queue_play_btn.clicked.connect(self._play_selected_queue_item)
        self.queue_up_btn = QPushButton("Move Up")
        self.queue_up_btn.clicked.connect(lambda: self._move_selected_queue_item(-1))
        self.queue_down_btn = QPushButton("Move Down")
        self.queue_down_btn.clicked.connect(lambda: self._move_selected_queue_item(1))
        self.queue_remove_btn = QPushButton("Remove")
        self.queue_remove_btn.clicked.connect(self._remove_selected_queue_items)
        self.queue_clear_btn = QPushButton("Clear Queue")
        self.queue_clear_btn.clicked.connect(self.player.clear_queue)

        buttons = QHBoxLayout()
        buttons.addWidget(self.queue_play_btn)
        buttons.addWidget(self.queue_up_btn)
        buttons.addWidget(self.queue_down_btn)
        buttons.addWidget(self.queue_remove_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.queue_clear_btn)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.addWidget(title)
        layout.addWidget(self.queue_list, 1)
        layout.addLayout(buttons)
        return panel

    def _refresh_queue(self) -> None:
        if not hasattr(self, "queue_list"):
            return
        selected_rows = {idx.row() for idx in self.queue_list.selectedIndexes()}
        self.queue_list.clear()
        current = self.player.current_index()
        for row, track in enumerate(self.player.queue()):
            prefix = "▶ " if row == current else "   "
            item = QListWidgetItem(
                f"{prefix}{row + 1:02d}. {track.title} — {track.display_artist}"
            )
            item.setData(Qt.UserRole, row)
            item.setToolTip(
                f"Artist: {track.display_artist}\n"
                f"Album: {track.album or 'Unknown Album'}\n"
                f"File location: {track.path}"
            )
            if row == current:
                item.setForeground(QColor("#72f4ff"))
            self.queue_list.addItem(item)
            if row in selected_rows:
                item.setSelected(True)
        self._update_queue_buttons()

    def _queue_selected_rows(self) -> list[int]:
        rows = [idx.row() for idx in self.queue_list.selectedIndexes()]
        return sorted(set(rows))

    def _play_queue_item(self, item: QListWidgetItem) -> None:
        self.player.play_index(item.data(Qt.UserRole))

    def _play_selected_queue_item(self) -> None:
        rows = self._queue_selected_rows()
        if rows:
            self.player.play_index(rows[0])

    def _move_selected_queue_item(self, offset: int) -> None:
        rows = self._queue_selected_rows()
        if len(rows) != 1:
            return
        row = rows[0]
        self.player.move_queue_item(row, row + offset)
        self.queue_list.setCurrentRow(max(0, min(row + offset, self.queue_list.count() - 1)))

    def _remove_selected_queue_items(self) -> None:
        self.player.remove_queue_indices(self._queue_selected_rows())

    def _update_queue_buttons(self) -> None:
        rows = self._queue_selected_rows()
        has_queue = self.queue_list.count() > 0
        has_selection = bool(rows)
        single = len(rows) == 1
        self.queue_play_btn.setEnabled(has_selection)
        self.queue_remove_btn.setEnabled(has_selection)
        self.queue_up_btn.setEnabled(single and rows[0] > 0)
        self.queue_down_btn.setEnabled(single and rows[0] < self.queue_list.count() - 1)
        self.queue_clear_btn.setEnabled(has_queue)

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


PLAY_BUTTON_SIZE = 62
SIDE_BUTTON_SIZE = (42, 40)


class PlayPauseButton(QToolButton):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._playing = False
        self.setText("")
        self.setAccessibleName("Play")
        self.setToolTip("Play/Pause")

    def set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        self.setAccessibleName("Pause" if playing else "Play")
        self.update()

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)

        r = self.rect()
        size = min(r.width(), r.height())
        if size <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))

        cx = r.center().x()
        cy = r.center().y()

        if self._playing:
            bar_w = max(6.0, size * 0.14)
            bar_h = size * 0.44
            gap = max(3.0, size * 0.06)
            top = cy - bar_h / 2
            left_x = cx - gap / 2 - bar_w
            right_x = cx + gap / 2
            radius = max(1.0, bar_w * 0.08)
            painter.drawRoundedRect(QRectF(left_x, top, bar_w, bar_h), radius, radius)
            painter.drawRoundedRect(QRectF(right_x, top, bar_w, bar_h), radius, radius)
            return

        icon_w = size * 0.46
        icon_h = size * 0.52
        left_x = cx - icon_w * 0.34
        right_x = cx + icon_w * 0.50
        path = QPainterPath()
        path.moveTo(left_x, cy - icon_h / 2)
        path.lineTo(right_x, cy)
        path.lineTo(left_x, cy + icon_h / 2)
        path.closeSubpath()
        painter.drawPath(path)


class TransportBar(QWidget):
    """Bottom playback area with controls contained inside the glossy capsule."""

    open_now_playing = Signal()

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

        self.shuffle_btn = self._make_btn("⤨")
        self.shuffle_btn.setToolTip("Shuffle")
        self.shuffle_btn.setCheckable(True)
        self.repeat_btn = self._make_btn("⟳")
        self.repeat_btn.setToolTip("Repeat")
        self.repeat_btn.setCheckable(True)
        self.stop_btn = self._make_btn("■")
        self.stop_btn.setToolTip("Stop")
        self.prev_btn = self._make_btn("◀◀")
        self.prev_btn.setToolTip("Previous")
        self.next_btn = self._make_btn("▶▶")
        self.next_btn.setToolTip("Next")

        self.play_btn = PlayPauseButton()
        self.play_btn.setObjectName("transportPlay")
        self.play_btn.setFixedSize(PLAY_BUTTON_SIZE, PLAY_BUTTON_SIZE)
        self.play_btn.clicked.connect(player.toggle)

        self.prev_btn.clicked.connect(player.previous)
        self.next_btn.clicked.connect(player.next)
        self.stop_btn.clicked.connect(player.stop)
        self.shuffle_btn.toggled.connect(player.set_shuffle)
        self.repeat_btn.clicked.connect(self._cycle_repeat)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        controls.addWidget(self.stop_btn)
        controls.addSpacing(4)
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
        self.vol.valueChanged.connect(player.set_volume)
        vol_icon = QLabel("♬")
        vol_icon.setObjectName("volumeIcon")
        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(8)
        vol_row.addWidget(vol_icon)
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

    def _make_btn(self, text: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setObjectName("transportBtn")
        b.setFixedSize(*SIDE_BUTTON_SIZE)
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

    def _on_state(self, state: str) -> None:
        self.play_btn.set_playing(state == "playing")

    def _on_seek_release(self) -> None:
        self.player.seek(self.seek.value())
        self._user_dragging = False
