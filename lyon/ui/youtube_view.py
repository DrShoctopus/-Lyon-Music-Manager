"""YouTube search-and-download tab — native Qt UI backed by yt-dlp.

No WebEngine / PySide6-Addons required. Results come from yt-dlp's search
backend; clicking a result opens the download dialog pre-populated with the
video URL.
"""
from __future__ import annotations

from importlib.util import find_spec

from PySide6.QtCore import QByteArray, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

HAS_YTDLP = find_spec("yt_dlp") is not None

_THUMB_W = 120
_THUMB_H = 68
_MAX_RESULTS = 15


def _fmt_duration(seconds) -> str:
    try:
        s = int(seconds)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except (TypeError, ValueError):
        return ""


def _fmt_views(n) -> str:
    try:
        n = int(n)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M views"
        if n >= 1_000:
            return f"{n // 1_000}K views"
        return f"{n} views"
    except (TypeError, ValueError):
        return ""


class _SearchWorker(QThread):
    results_ready = Signal(list)
    error = Signal(str)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self) -> None:
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{_MAX_RESULTS}:{self._query}", download=False)
            entries = (info.get("entries") or []) if info else []
            results = []
            for e in entries:
                thumb = e.get("thumbnail") or ""
                if not thumb:
                    for t in e.get("thumbnails") or []:
                        thumb = t.get("url", "")
                        if thumb:
                            break
                results.append({
                    "title": e.get("title") or "(no title)",
                    "channel": e.get("channel") or e.get("uploader") or "",
                    "duration": _fmt_duration(e.get("duration")),
                    "views": _fmt_views(e.get("view_count")),
                    "url": e.get("webpage_url") or e.get("url") or "",
                    "thumbnail": thumb,
                })
            self.results_ready.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _ResultRow(QWidget):
    """Single result row: thumbnail on the left, metadata stacked on the right."""

    def __init__(self, data: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.url = data["url"]

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet("background:#0a0e13; border-radius:3px;")
        row.addWidget(self._thumb)

        meta = QVBoxLayout()
        meta.setSpacing(3)

        title = QLabel(data["title"])
        title.setStyleSheet("color:#72f4ff; font-weight:600; font-size:10pt;")
        title.setWordWrap(True)
        meta.addWidget(title)

        if data["channel"]:
            ch = QLabel(data["channel"])
            ch.setStyleSheet("color:#8a9bb0; font-size:9pt;")
            meta.addWidget(ch)

        detail_parts = [p for p in (data["duration"], data["views"]) if p]
        if detail_parts:
            detail = QLabel("  ·  ".join(detail_parts))
            detail.setStyleSheet("color:#65707c; font-size:9pt;")
            meta.addWidget(detail)

        meta.addStretch(1)
        row.addLayout(meta, 1)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self._thumb.setPixmap(
            pixmap.scaled(_THUMB_W, _THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class YouTubeView(QWidget):
    """YouTube search-and-download tab (no WebEngine dependency)."""

    download_requested = Signal(str)  # emits the video URL when a result is clicked

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: _SearchWorker | None = None
        self._nam = QNetworkAccessManager(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- search bar
        nav = QHBoxLayout()
        nav.setContentsMargins(10, 8, 10, 8)
        nav.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search YouTube…")
        self.search.returnPressed.connect(self._on_search)

        self._search_btn = QPushButton("Search")
        self._search_btn.setObjectName("accent")
        self._search_btn.clicked.connect(self._on_search)

        nav.addWidget(self.search, 1)
        nav.addWidget(self._search_btn)
        layout.addLayout(nav)

        # ---- status line (searching…)
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#8a9bb0; font-size:9pt; padding:2px 10px;")
        self._status.hide()
        layout.addWidget(self._status)

        # ---- results list
        self._list = QListWidget()
        self._list.setSpacing(1)
        self._list.setStyleSheet(
            "QListWidget { background:#0a0e13; border:none; outline:none; }"
            "QListWidget::item { border-bottom:1px solid #1a2230; }"
            "QListWidget::item:selected { background:#1466c7; }"
            "QListWidget::item:hover:!selected { background:#111c2a; }"
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.hide()
        layout.addWidget(self._list, 1)

        # ---- placeholder shown before the first search
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignCenter)
        if HAS_YTDLP:
            self._hint.setText(
                "Search for an artist, album, or track above.\n"
                "Click a result to open the download dialog."
            )
            self._hint.setStyleSheet("color:#3a4a5a; font-size:11pt;")
        else:
            self._hint.setText(
                "yt-dlp is not installed.\n\nInstall it with:\n    pip install yt-dlp"
            )
            self._hint.setStyleSheet("color:#72f4ff; font-size:11pt;")
            self.search.setEnabled(False)
            self._search_btn.setEnabled(False)
        layout.addWidget(self._hint, 1)

    # ------------------------------------------------------------------ public API

    def search_youtube(self, text: str) -> bool:
        """Populate the search field and run a search. Returns False if unavailable."""
        text = text.strip()
        if not text or not HAS_YTDLP:
            return False
        self.search.setText(text)
        self._run_search(text)
        return True

    def pause_all_videos(self) -> None:
        """No-op — kept for API compatibility with MainWindow."""

    # ------------------------------------------------------------------ internals

    def _on_search(self) -> None:
        text = self.search.text().strip()
        if text and HAS_YTDLP:
            self._run_search(text)

    def _run_search(self, query: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.results_ready.disconnect()
            self._worker.error.disconnect()
            self._worker.quit()

        self._list.clear()
        self._list.hide()
        self._hint.hide()
        self._status.setText("Searching…")
        self._status.show()
        self._search_btn.setEnabled(False)

        self._worker = _SearchWorker(query, self)
        self._worker.results_ready.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._search_btn.setEnabled(True))
        self._worker.start()

    def _on_results(self, results: list) -> None:
        self._status.hide()
        self._list.clear()

        if not results:
            self._hint.setText("No results found.")
            self._hint.show()
            return

        for data in results:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, _THUMB_H + 16))
            item.setData(Qt.UserRole, data["url"])
            self._list.addItem(item)
            row = _ResultRow(data)
            self._list.setItemWidget(item, row)
            if data["thumbnail"]:
                self._fetch_thumbnail(data["thumbnail"], row)

        self._list.show()

    def _on_error(self, msg: str) -> None:
        self._status.hide()
        self._hint.setText(f"Search failed:\n{msg}")
        self._hint.show()

    def _fetch_thumbnail(self, url: str, row: _ResultRow) -> None:
        req = QNetworkRequest(QUrl(url))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._apply_thumbnail(reply, row))

    def _apply_thumbnail(self, reply: QNetworkReply, row: _ResultRow) -> None:
        if reply.error() == QNetworkReply.NetworkError.NoError:
            px = QPixmap()
            if px.loadFromData(QByteArray(reply.readAll())):
                row.set_thumbnail(px)
        reply.deleteLater()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.UserRole)
        if url:
            self.download_requested.emit(url)
