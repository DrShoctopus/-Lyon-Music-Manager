"""Now Playing view + bottom transport bar."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy,
    QSlider, QToolButton, QVBoxLayout, QWidget,
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addStretch(1)
        layout.addLayout(top)
        layout.addStretch(1)

        player.track_changed.connect(self._on_track)

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


# Vertical lift of the play button above the bar's top edge, in pixels.
PLAY_BUTTON_LIFT = 28


class TransportBar(QWidget):
    """Bottom playback area: a visible bar + a raised play button.

    The wrapper is taller than the visible bar; the bar itself fills the
    bottom portion, and the play button is a free-floating child that
    sits centred over the controls and protrudes above the bar's top
    edge -- the classic WMP raised-circle look.
    """

    open_now_playing = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None):
        super().__init__(parent)
        self.player = player
        self._user_dragging = False

        # The visible bar -- gradient background, border-top, etc.
        self.bar = QFrame(self)
        self.bar.setObjectName("transport")

        # Compact cover thumb; the transport is now a slim glossy pill, so the
        # artwork acts as a small quick-link into Now Playing instead of a large
        # block that makes the bar feel heavy.
        self.thumb = QLabel()
        self.thumb.setObjectName("transportThumb")
        self.thumb.setFixedSize(76, 76)
        self.thumb.setPixmap(cover_pixmap(None, 76, "♪"))
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
        meta_w.setMinimumWidth(220)
        meta_w.setMaximumWidth(360)
        meta_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Side transport buttons (live in the bar's layout). They are ordered
        # like the reference: utility controls on the left, seek controls around
        # a raised central play button, and volume on the right.
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

        # Play button: free-floating child of self (the wrapper, NOT the bar)
        # so it can protrude above the bar's top edge without being clipped.
        self.play_btn = QToolButton(self)
        self.play_btn.setObjectName("transportPlay")
        self.play_btn.setText("▶")
        self.play_btn.clicked.connect(player.toggle)

        self.prev_btn.clicked.connect(player.previous)
        self.next_btn.clicked.connect(player.next)
        self.stop_btn.clicked.connect(player.stop)
        self.shuffle_btn.toggled.connect(player.set_shuffle)
        self.repeat_btn.clicked.connect(self._cycle_repeat)

        # Reserve horizontal space in the controls row where the play button
        # visually sits. Width matches the play button, height matches the
        # side buttons so the row's centerline does not shift.
        self._play_spacer = QWidget()

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(self.shuffle_btn)
        controls.addWidget(self.repeat_btn)
        controls.addWidget(self.stop_btn)
        controls.addSpacing(8)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self._play_spacer)
        controls.addWidget(self.next_btn)

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
        self.vol.setObjectName("volumeSlider")
        self.vol.setMaximumWidth(260)
        self.vol.valueChanged.connect(player.set_volume)
        vol_icon = QLabel("♬")
        vol_icon.setObjectName("volumeIcon")
        vol_row = QHBoxLayout()
        vol_row.setSpacing(10)
        vol_row.addWidget(vol_icon)
        vol_row.addWidget(self.vol)

        # The bar's own internal layout.
        bar_layout = QHBoxLayout(self.bar)
        bar_layout.setContentsMargins(20, 12, 20, 12)
        bar_layout.setSpacing(14)
        bar_layout.addWidget(self.thumb)
        bar_layout.addWidget(meta_w)
        bar_layout.addStretch(1)
        bar_layout.addLayout(center, 3)
        bar_layout.addStretch(1)
        bar_layout.addLayout(vol_row)

        # Wrapper layout: leave PLAY_BUTTON_LIFT pixels of breathing room
        # above the bar so the protruding play button has somewhere to render.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, PLAY_BUTTON_LIFT, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.bar)

        player.track_changed.connect(self._on_track)
        player.position_changed.connect(self._on_position)
        player.state_changed.connect(self._on_state)

        # Initial spacer sizing & button raise so the first paint is correct.
        self._sync_spacer_size()
        self.play_btn.raise_()

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
            self.thumb.setPixmap(cover_pixmap(None, 76, "♪"))
        else:
            self.title_lbl.setText(track.title)
            self.artist_lbl.setText(f"{track.display_artist} - {track.album}")
            self.thumb.setPixmap(cover_pixmap(track.artwork_path, 76, "♪"))

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

    # ---- Floating play button positioning -----------------------------------

    def _sync_spacer_size(self) -> None:
        """Reserve a row slot the same width as the play button."""
        play_hint = self.play_btn.sizeHint()
        # Width matches the play button so the controls row stays symmetric.
        # Height matches the side buttons so the row's centerline does not
        # shift -- the play button is allowed to extend above instead.
        self._play_spacer.setFixedSize(play_hint.width(), 54)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._reposition_play_button()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._sync_spacer_size()
        self._reposition_play_button()

    def _reposition_play_button(self) -> None:
        """Centre the play button over the spacer, lifted above the bar."""
        spacer = self._play_spacer
        if not spacer.isVisible():
            return
        play_hint = self.play_btn.sizeHint()
        bw, bh = play_hint.width(), play_hint.height()
        if bw <= 0 or bh <= 0:
            return
        self.play_btn.resize(bw, bh)
        # Spacer position is in the bar's coordinates; map to self (wrapper).
        anchor = spacer.mapTo(self, QPoint(0, 0))
        x = anchor.x() + (spacer.width() - bw) // 2
        # Vertically centre the play button on the spacer, then lift.
        y = anchor.y() + (spacer.height() - bh) // 2 - PLAY_BUTTON_LIFT
        self.play_btn.move(x, y)
        self.play_btn.raise_()
