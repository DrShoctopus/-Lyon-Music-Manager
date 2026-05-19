from __future__ import annotations

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.radio import RadioStation
from lyon.core.settings import Settings
from lyon.ui import radio_view as radio_view_module
from lyon.ui.radio_view import RadioView


def test_radio_view_renders_saved_stations_and_filters(qapp):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live", "genre": "Jazz"},
            {"name": "Sea News", "url": "https://news.example.test/live", "genre": "News"},
        ]
    )
    view = RadioView(settings)

    try:
        assert view.table.rowCount() == 2
        view.search.setText("jazz")
        assert not view.table.isRowHidden(0)
        assert view.table.isRowHidden(1)
        assert view.footer_label.text() == "1/2 stations"
    finally:
        view.deleteLater()


def test_radio_view_play_selected_emits_url_and_remembers_stream(qapp, monkeypatch):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Radio", "url": "https://radio.example.test/live"},
        ]
    )
    saves: list[bool] = []
    monkeypatch.setattr(settings, "save", lambda: saves.append(True))
    view = RadioView(settings)
    played: list[tuple[str, str]] = []
    view.play_requested.connect(lambda url, title: played.append((url, title)))

    try:
        view.table.selectRow(0)
        view._play_selected()

        assert played == [("https://radio.example.test/live", "Sea Radio")]
        assert settings.recent_stream_urls == ["https://radio.example.test/live"]
        assert saves == [True]
    finally:
        view.deleteLater()


def test_radio_view_add_station_dialog_persists_station(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)

    class FakeDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def station(self):
            return RadioStation("Added", "https://added.example.test/live", "Rock")

        def deleteLater(self):
            pass

    monkeypatch.setattr(radio_view_module, "_StationDialog", FakeDialog)
    view = RadioView(settings)

    try:
        view._add_station()

        assert settings.radio_stations == [{
            "name": "Added",
            "url": "https://added.example.test/live",
            "genre": "Rock",
            "bitrate": 0,
        }]
        assert view.table.rowCount() == 1
    finally:
        view.deleteLater()


def test_radio_view_import_playlist_persists_stations(qapp, monkeypatch, tmp_path):
    playlist = tmp_path / "stations.pls"
    playlist.write_text(
        "[playlist]\n"
        "File1=https://one.example.test/live\n"
        "Title1=One\n"
        "File2=https://two.example.test/live\n"
        "Title2=Two\n",
        encoding="utf-8",
    )
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    monkeypatch.setattr(
        radio_view_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(playlist), ""),
    )
    view = RadioView(settings)

    try:
        view._import_playlist()

        assert [station["name"] for station in settings.radio_stations] == ["One", "Two"]
        assert view.table.rowCount() == 2
    finally:
        view.deleteLater()


def test_radio_view_remove_selected_station(qapp, monkeypatch):
    settings = Settings(
        radio_stations=[
            {"name": "One", "url": "https://one.example.test/live"},
            {"name": "Two", "url": "https://two.example.test/live"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view.table.selectRow(0)
        view._remove_selected()

        assert settings.radio_stations == [{
            "name": "Two",
            "url": "https://two.example.test/live",
            "genre": "",
            "bitrate": 0,
        }]
        assert view.table.rowCount() == 1
    finally:
        view.deleteLater()
