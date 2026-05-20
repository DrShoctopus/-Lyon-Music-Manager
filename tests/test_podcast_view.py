from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.podcast import PodcastEpisode, PodcastFeed
from lyon.core.settings import Settings
from lyon.ui import podcast_view as podcast_view_module
from lyon.ui.podcast_view import PodcastView


def _episode(title: str = "Episode One") -> PodcastEpisode:
    return PodcastEpisode(
        feed_title="Sea Stories",
        feed_url="https://podcasts.example.test/feed.xml",
        title=title,
        url="https://podcasts.example.test/audio/one.mp3",
        published="2026-05-19",
        duration="12:34",
    )


def test_podcast_view_applies_refresh_results_and_filters(qapp, monkeypatch):
    settings = Settings(
        podcast_subscriptions=[
            {"title": "Sea Stories", "url": "https://podcasts.example.test/feed.xml"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = PodcastView(settings)

    try:
        view._apply_refresh_results(
            [PodcastFeed("Sea Stories", url="https://podcasts.example.test/feed.xml")],
            [_episode("Launch Day"), _episode("Harbor Notes")],
            [],
        )

        assert view.table.rowCount() == 2
        assert settings.podcast_subscriptions[0]["title"] == "Sea Stories"
        view.search.setText("harbor")
        assert view.table.isRowHidden(0)
        assert not view.table.isRowHidden(1)
        assert view.footer_label.text() == "1/2 episodes"
    finally:
        view.deleteLater()


def test_podcast_view_play_selected_emits_url_and_remembers_stream(qapp, monkeypatch):
    settings = Settings(
        podcast_subscriptions=[
            {"title": "Sea Stories", "url": "https://podcasts.example.test/feed.xml"},
        ]
    )
    saves: list[bool] = []
    monkeypatch.setattr(settings, "save", lambda: saves.append(True))
    view = PodcastView(settings)
    played: list[tuple[str, str]] = []
    view.play_requested.connect(lambda url, title: played.append((url, title)))

    try:
        view._apply_refresh_results([], [_episode()], [])
        saves.clear()
        view.table.selectRow(0)
        view._play_selected()

        assert played == [(
            "https://podcasts.example.test/audio/one.mp3",
            "Sea Stories - Episode One",
        )]
        assert settings.recent_stream_urls == ["https://podcasts.example.test/audio/one.mp3"]
        assert saves == [True]
    finally:
        view.deleteLater()


def test_podcast_view_add_podcast_fetches_and_persists_feed(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)

    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def url(self):
            return "https://podcasts.example.test/feed.xml"

        def deleteLater(self):
            pass

    monkeypatch.setattr(podcast_view_module, "_PodcastDialog", FakeDialog)
    monkeypatch.setattr(
        podcast_view_module,
        "fetch_feed",
        lambda _url: PodcastFeed(
            "Sea Stories",
            url="https://podcasts.example.test/feed.xml",
            episodes=(_episode(),),
        ),
    )
    view = PodcastView(settings)

    try:
        view._add_podcast()

        assert settings.podcast_subscriptions == [{
            "title": "Sea Stories",
            "url": "https://podcasts.example.test/feed.xml",
            "homepage": "",
            "description": "",
            "artwork_url": "",
        }]
        assert view.table.rowCount() == 1
    finally:
        view.deleteLater()


def test_podcast_view_import_opml_persists_subscriptions(qapp, monkeypatch, tmp_path):
    opml = tmp_path / "podcasts.opml"
    opml.write_text(
        """<opml version="2.0"><body>
          <outline text="One" xmlUrl="https://one.example.test/feed.xml" />
          <outline text="Two" xmlUrl="https://two.example.test/feed.xml" />
        </body></opml>""",
        encoding="utf-8",
    )
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    monkeypatch.setattr(
        podcast_view_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(opml), ""),
    )
    refreshes: list[bool] = []
    monkeypatch.setattr(PodcastView, "refresh", lambda self: refreshes.append(True))
    view = PodcastView(settings)

    try:
        view._import_opml()

        assert [sub["title"] for sub in settings.podcast_subscriptions] == ["One", "Two"]
        assert refreshes == [True]
    finally:
        view.deleteLater()


def test_podcast_view_import_opml_handles_parse_errors(qapp, monkeypatch, tmp_path):
    opml = tmp_path / "broken.opml"
    opml.write_text("<opml><body>", encoding="utf-8")
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    monkeypatch.setattr(
        podcast_view_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(opml), ""),
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        podcast_view_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    view = PodcastView(settings)

    try:
        view._import_opml()

        assert settings.podcast_subscriptions == []
        assert warnings == [("Import Podcast OPML", "Could not read broken.opml.")]
    finally:
        view.deleteLater()


def test_podcast_view_remove_selected_feed(qapp, monkeypatch):
    settings = Settings(
        podcast_subscriptions=[
            {"title": "Sea Stories", "url": "https://podcasts.example.test/feed.xml"},
            {"title": "Other", "url": "https://other.example.test/feed.xml"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = PodcastView(settings)

    try:
        view._apply_refresh_results([], [_episode()], [])
        view.table.selectRow(0)
        view._remove_selected_feed()

        assert settings.podcast_subscriptions == [{
            "title": "Other",
            "url": "https://other.example.test/feed.xml",
            "homepage": "",
            "description": "",
            "artwork_url": "",
        }]
        assert view.table.rowCount() == 0
    finally:
        view.deleteLater()


def test_podcast_view_ignores_refresh_results_for_removed_feed(qapp, monkeypatch):
    settings = Settings(
        podcast_subscriptions=[
            {"title": "Other", "url": "https://other.example.test/feed.xml"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = PodcastView(settings)

    try:
        view._apply_refresh_results(
            [PodcastFeed("Sea Stories", url="https://podcasts.example.test/feed.xml")],
            [_episode()],
            [],
        )

        assert [sub["title"] for sub in settings.podcast_subscriptions] == ["Other"]
        assert view.table.rowCount() == 0
    finally:
        view.deleteLater()


def test_podcast_view_shutdown_interrupts_refresh_thread(qapp):
    settings = Settings()
    view = PodcastView(settings)

    class FakeThread:
        def __init__(self, wait_result: bool):
            self.wait_result = wait_result
            self.interrupted = False
            self.waited_ms = None
            self.deleted = False

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def wait(self, timeout_ms):
            self.waited_ms = timeout_ms
            return self.wait_result

        def deleteLater(self):
            self.deleted = True

    try:
        thread = FakeThread(True)
        view._refresh_thread = thread
        assert view.shutdown(1234) is True
        assert thread.interrupted is True
        assert thread.waited_ms == 1234
        assert thread.deleted is True
        assert view._refresh_thread is None

        blocked = FakeThread(False)
        view._refresh_thread = blocked
        assert view.shutdown(7) is False
        assert blocked.interrupted is True
        assert blocked.waited_ms == 7
        assert view._refresh_thread is blocked
    finally:
        view._refresh_thread = None
        view.deleteLater()
