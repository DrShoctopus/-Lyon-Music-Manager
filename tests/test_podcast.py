from __future__ import annotations

from lyon.core import podcast
from lyon.core.podcast import fetch_feed, parse_feed_text, parse_opml_text, subscription_from_settings
from lyon.core.settings import Settings, normalize_podcast_subscriptions


def test_parse_rss_feed_reads_show_metadata_and_audio_enclosures():
    feed = parse_feed_text(
        """<?xml version="1.0"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
          <channel>
            <title>Sea Stories</title>
            <link>https://podcasts.example.test</link>
            <description>Stories from the coast.</description>
            <itunes:image href="/cover.jpg" />
            <item>
              <title>Launch Day</title>
              <guid>episode-1</guid>
              <pubDate>Tue, 19 May 2026 12:00:00 GMT</pubDate>
              <itunes:duration>3723</itunes:duration>
              <enclosure url="/audio/launch.mp3" type="audio/mpeg" />
            </item>
            <item>
              <title>Transcript Only</title>
              <link>https://podcasts.example.test/no-audio</link>
            </item>
          </channel>
        </rss>
        """,
        source_url="https://podcasts.example.test/feed.xml",
    )

    assert feed.title == "Sea Stories"
    assert feed.homepage == "https://podcasts.example.test"
    assert feed.artwork_url == "https://podcasts.example.test/cover.jpg"
    assert len(feed.episodes) == 1
    episode = feed.episodes[0]
    assert episode.feed_title == "Sea Stories"
    assert episode.feed_url == "https://podcasts.example.test/feed.xml"
    assert episode.title == "Launch Day"
    assert episode.url == "https://podcasts.example.test/audio/launch.mp3"
    assert episode.guid == "episode-1"
    assert episode.published == "2026-05-19"
    assert episode.duration == "1:02:03"


def test_fetch_feed_uses_bounded_response_read(monkeypatch):
    calls: list[int] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

        def read(self, size=-1):
            calls.append(size)
            return b"<rss><channel><title>Bounded</title></channel></rss>"

    monkeypatch.setattr(podcast, "MAX_FEED_SIZE", 64)
    monkeypatch.setattr(podcast, "urlopen", lambda _request, timeout: Response())

    feed = fetch_feed("https://podcasts.example.test/feed.xml")

    assert feed.title == "Bounded"
    assert calls == [65]


def test_fetch_feed_rejects_responses_larger_than_limit(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

        def read(self, size=-1):
            return b"x" * size

    monkeypatch.setattr(podcast, "MAX_FEED_SIZE", 64)
    monkeypatch.setattr(podcast, "urlopen", lambda _request, timeout: Response())

    try:
        fetch_feed("https://podcasts.example.test/feed.xml")
    except ValueError as exc:
        assert "too large" in str(exc)
    else:
        raise AssertionError("oversized feed should raise ValueError")


def test_parse_rss_feed_quotes_spaces_in_episode_urls():
    feed = parse_feed_text(
        """<rss version="2.0">
          <channel>
            <title>Sea Stories</title>
            <item>
              <title>Launch Day</title>
              <enclosure url="/audio/launch day.mp3?token=one two" type="audio/mpeg" />
            </item>
          </channel>
        </rss>
        """,
        source_url="https://podcasts.example.test/feed.xml",
    )

    assert feed.episodes[0].url == "https://podcasts.example.test/audio/launch%20day.mp3?token=one%20two"


def test_parse_atom_feed_reads_enclosure_links():
    feed = parse_feed_text(
        """<feed xmlns="http://www.w3.org/2005/Atom">
          <title>Atom Audio</title>
          <link rel="alternate" href="https://atom.example.test" />
          <entry>
            <id>tag:atom.example.test,2026:1</id>
            <title>First Entry</title>
            <published>2026-05-18T09:30:00Z</published>
            <link rel="enclosure" href="episodes/first.opus" type="audio/ogg" />
          </entry>
        </feed>""",
        source_url="https://atom.example.test/feed.atom",
    )

    assert feed.homepage == "https://atom.example.test"
    assert feed.episodes[0].url == "https://atom.example.test/episodes/first.opus"
    assert feed.episodes[0].published == "2026-05-18"


def test_parse_opml_extracts_and_dedupes_feed_urls():
    subscriptions = parse_opml_text(
        """<opml version="2.0">
          <body>
            <outline text="Tech">
              <outline type="rss" text="One" xmlUrl="https://one.example.test/feed.xml" />
              <outline type="rss" title="Duplicate" xmlUrl="https://one.example.test/feed.xml" />
              <outline type="rss" text="Bad" xmlUrl="file:///tmp/feed.xml" />
            </outline>
          </body>
        </opml>"""
    )

    assert [sub.title for sub in subscriptions] == ["One"]
    assert subscriptions[0].url == "https://one.example.test/feed.xml"


def test_parse_opml_wraps_malformed_xml_as_value_error():
    try:
        parse_opml_text("<opml><body>")
    except ValueError as exc:
        assert "Invalid OPML XML" in str(exc)
    else:
        raise AssertionError("malformed OPML should raise ValueError")


def test_parse_opml_rejects_xml_entities():
    try:
        parse_opml_text(
            """<!DOCTYPE opml [<!ENTITY boom "boom">]>
            <opml version="2.0"><body><outline text="&boom;" /></body></opml>"""
        )
    except ValueError as exc:
        assert "Invalid OPML XML" in str(exc)
    else:
        raise AssertionError("entity-bearing OPML should raise ValueError")


def test_podcast_subscription_settings_normalize_and_merge():
    settings = Settings(
        podcast_subscriptions=[
            {
                "title": "Original",
                "url": "https://pod.example.test/feed.xml",
                "description": "keep",
            },
            {"title": "Bad", "url": "file:///tmp/feed.xml"},
        ]
    )

    settings.add_podcast_subscriptions([
        {
            "title": "Updated",
            "url": "https://pod.example.test/feed.xml",
            "artwork_url": "https://pod.example.test/cover.jpg",
        },
        {"title": "Second", "url": "https://second.example.test/feed.xml"},
    ])

    assert normalize_podcast_subscriptions("bad") == []
    assert settings.podcast_subscriptions == [
        {
            "title": "Updated",
            "url": "https://pod.example.test/feed.xml",
            "homepage": "",
            "description": "keep",
            "artwork_url": "https://pod.example.test/cover.jpg",
        },
        {
            "title": "Second",
            "url": "https://second.example.test/feed.xml",
            "homepage": "",
            "description": "",
            "artwork_url": "",
        },
    ]


def test_subscription_from_settings_rejects_invalid_feed_urls():
    assert subscription_from_settings({"title": "Bad", "url": "file:///tmp/feed.xml"}) is None
    sub = subscription_from_settings({"url": "https://pod.example.test/feed.xml"})
    assert sub is not None
    assert sub.title == "https://pod.example.test/feed.xml"
