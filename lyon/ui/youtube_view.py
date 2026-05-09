"""YouTube view: embeds youtube.com in a QWebEngineView.

Requires PySide6-Addons (QtWebEngine + Chromium). When unavailable we fall
back to a friendly message instead of crashing the whole app.
"""
from __future__ import annotations

from importlib.util import find_spec

from PySide6.QtCore import QUrl, Qt, QUrlQuery
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

HAS_WEBENGINE = (
    find_spec("PySide6.QtWebEngineWidgets") is not None
    and find_spec("PySide6.QtWebEngineCore") is not None
)

if HAS_WEBENGINE:  # pragma: no cover - optional dependency
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings


YT_HOME = "https://www.youtube.com/"


class YouTubeView(QWidget):
    """In-app YouTube browser using QtWebEngine.

    Top bar mirrors WMP's row of accent buttons: back / forward / reload, a
    URL/search field, and a Home shortcut. Videos play full size below.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        if not HAS_WEBENGINE:
            self._build_unavailable_ui()
            return

        # Top nav row -- back / forward / reload, search, home
        nav = QHBoxLayout()
        nav.setContentsMargins(10, 8, 10, 8)
        self.back_btn = QPushButton("←")
        self.fwd_btn = QPushButton("→")
        self.reload_btn = QPushButton("↻")
        for b in (self.back_btn, self.fwd_btn, self.reload_btn):
            b.setFixedWidth(40)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search YouTube or paste a URL...")
        self.search.returnPressed.connect(self._on_search)

        self.home_btn = QPushButton("Home")
        self.home_btn.setObjectName("accent")
        self.home_btn.clicked.connect(lambda: self.web.load(QUrl(YT_HOME)))

        nav.addWidget(self.back_btn)
        nav.addWidget(self.fwd_btn)
        nav.addWidget(self.reload_btn)
        nav.addWidget(self.search, 1)
        nav.addWidget(self.home_btn)

        # Web view
        profile = QWebEngineProfile.defaultProfile()
        s = profile.settings()
        # Allow autoplay so videos start when the user clicks play.
        s.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)

        self.web = QWebEngineView(self)
        self.web.load(QUrl(YT_HOME))

        self.back_btn.clicked.connect(self.web.back)
        self.fwd_btn.clicked.connect(self.web.forward)
        self.reload_btn.clicked.connect(self.web.reload)
        self.web.urlChanged.connect(self._on_url_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(nav)
        layout.addWidget(self.web, 1)

    def _build_unavailable_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("YouTube playback requires PySide6-Addons")
        f = title.font(); f.setPointSize(14); f.setBold(True); title.setFont(f)
        title.setStyleSheet("color:#ffb24d;")
        title.setAlignment(Qt.AlignCenter)
        body = QLabel(
            "QtWebEngine is not installed in this environment. Install it with:\n\n"
            "    pip install PySide6-Addons\n\n"
            "and restart the app."
        )
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet("color:#cfd6e2;")
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)

    def _on_search(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        # If the user pasted a URL, navigate to it directly.
        if text.startswith(("http://", "https://")):
            self.web.load(QUrl(text))
            return
        url = QUrl("https://www.youtube.com/results")
        query = QUrlQuery()
        query.addQueryItem("search_query", text)
        url.setQuery(query)
        self.web.load(url)

    def _on_url_changed(self, url: QUrl) -> None:
        s = url.toString()
        if "search_query=" in s:
            q = QUrlQuery(url).queryItemValue("search_query")
            if q:
                self.search.setText(q.replace("+", " "))
                return
        self.search.setText(s)

    def pause_all_videos(self) -> None:
        """Pause every <video> element on the current page.

        Called when the user navigates away from the YouTube tab so that
        playback stops and audio doesn't continue in the background.
        """
        if not HAS_WEBENGINE:
            return
        page = self.web.page() if hasattr(self, "web") else None
        if page is None:
            return
        page.runJavaScript(
            "document.querySelectorAll('video').forEach(v => v.pause());"
        )
