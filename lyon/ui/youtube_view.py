"""YouTube view: embeds youtube.com in a QWebEngineView.

Requires PySide6-Addons (QtWebEngine + Chromium). When unavailable we fall
back to a friendly message instead of crashing the whole app.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
    HAS_WEBENGINE = True
except ImportError:  # pragma: no cover - optional dep
    HAS_WEBENGINE = False
    QWebEngineView = None  # type: ignore[assignment]


YT_HOME = "https://www.youtube.com/"


class YouTubeView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        if not HAS_WEBENGINE:
            self._build_unavailable_ui()
            return

        # Top bar: back, forward, reload, address-ish bar
        nav = QHBoxLayout()
        nav.setContentsMargins(12, 10, 12, 10)
        self.back_btn = QPushButton("←")
        self.fwd_btn = QPushButton("→")
        self.reload_btn = QPushButton("↻")
        for b in (self.back_btn, self.fwd_btn, self.reload_btn):
            b.setObjectName("ghost")
            b.setFixedWidth(36)
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setPlaceholderText("Search YouTube...")
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
        # Allow autoplay so videos start when the user clicks play.
        s = profile.settings()
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
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignCenter)
        body = QLabel(
            "QtWebEngine isn't installed in this environment. Install it with:\n\n"
            "    pip install PySide6-Addons\n\n"
            "and restart the app."
        )
        body.setAlignment(Qt.AlignCenter)
        body.setStyleSheet("color:#b3b3b3; font-size:11pt;")
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)

    def _on_search(self) -> None:
        if not HAS_WEBENGINE:
            return
        q = self.search.text().strip()
        if not q:
            return
        url = QUrl("https://www.youtube.com/results")
        from PySide6.QtCore import QUrlQuery
        query = QUrlQuery()
        query.addQueryItem("search_query", q)
        url.setQuery(query)
        self.web.load(url)

    def _on_url_changed(self, url: QUrl) -> None:
        # Show the current page URL in the search bar when the user navigates.
        # If they're on a results page, show the query they typed.
        if "search_query=" in url.toString():
            from PySide6.QtCore import QUrlQuery
            q = QUrlQuery(url).queryItemValue("search_query")
            if q:
                self.search.setText(q.replace("+", " "))
                return
        self.search.setText(url.toString())
