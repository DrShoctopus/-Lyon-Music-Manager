from __future__ import annotations

import pytest
from unittest.mock import patch

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.radio import RadioStation
from lyon.core.settings import Settings
from lyon.ui import radio_view as radio_view_module
from lyon.ui import radio_station_dialog as radio_station_dialog_module
from lyon.ui.radio_view import _COL_STATUS, RadioView


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


def test_radio_view_filter_disables_hidden_selection(qapp, monkeypatch):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live", "genre": "Jazz"},
            {"name": "Sea News", "url": "https://news.example.test/live", "genre": "News"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)
    played: list[tuple[str, str]] = []
    view.play_requested.connect(lambda url, title: played.append((url, title)))

    try:
        view.table.selectRow(0)
        view.search.setText("news")

        assert view.table.isRowHidden(0)
        assert not view.play_btn.isEnabled()
        assert not view.remove_btn.isEnabled()

        view._play_selected()

        assert played == []
        assert settings.recent_stream_urls == []
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

    monkeypatch.setattr(radio_view_module, "RadioStationDialog", FakeDialog)
    view = RadioView(settings)

    try:
        view._add_station()

        assert settings.radio_stations == [{
            "name": "Added",
            "url": "https://added.example.test/live",
            "genre": "Rock",
            "bitrate": 0,
            "favorite": False,
            "tags": [],
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
    monkeypatch.setattr(
        radio_view_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QtWidgets.QMessageBox.Yes,
    )
    view = RadioView(settings)

    try:
        view.table.selectRow(0)
        view._remove_selected()

        assert settings.radio_stations == [{
            "name": "Two",
            "url": "https://two.example.test/live",
            "genre": "",
            "bitrate": 0,
            "favorite": False,
            "tags": [],
        }]
        assert view.table.rowCount() == 1
    finally:
        view.deleteLater()


# ---- PR4: Favorites & Tags ---------------------------------------------------

def test_radio_view_filter_searches_tags(qapp):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live", "tags": ["jazz", "smooth"]},
            {"name": "Sea News", "url": "https://news.example.test/live", "tags": ["news"]},
        ]
    )
    view = RadioView(settings)

    try:
        view.search.setText("smooth")
        hidden = [view.table.isRowHidden(r) for r in range(view.table.rowCount())]
        # Exactly one row should be visible
        assert hidden.count(False) == 1
    finally:
        view.deleteLater()


def test_radio_view_toggle_favorite_persists(qapp, monkeypatch):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        # Initially not a favorite
        assert settings.radio_stations[0].get("favorite") is False

        # Simulate clicking the favorite column on row 0
        view.table.selectRow(0)
        view._on_cell_clicked(0, 0)  # col 0 = _COL_FAVORITE

        assert settings.radio_stations[0]["favorite"] is True

        # Click again to un-favorite
        view._on_cell_clicked(0, 0)
        assert settings.radio_stations[0]["favorite"] is False
    finally:
        view.deleteLater()


# ---- PR5: Station health check ----------------------------------------------

def test_radio_view_health_result_updates_cell(qapp, monkeypatch):
    """_on_health_result stores in cache and updates the Status cell."""
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    view = RadioView(settings)

    try:
        # Simulate a successful health-check result arriving on the GUI thread.
        view._on_health_result("https://jazz.example.test/live", True, 200)

        status_item = view.table.item(0, _COL_STATUS)
        assert status_item is not None
        assert "●" in status_item.text()
        assert "200" in status_item.toolTip()
    finally:
        view.deleteLater()


def test_radio_view_health_failed_result_shown(qapp):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    view = RadioView(settings)

    try:
        view._on_health_result("https://jazz.example.test/live", False, 404)

        status_item = view.table.item(0, _COL_STATUS)
        assert status_item is not None
        assert "●" in status_item.text()
        assert "404" in status_item.toolTip()
        # Red foreground
        color = status_item.foreground().color()
        assert color.red() > color.green()  # red > green → reddish
    finally:
        view.deleteLater()


def test_radio_view_unknown_status_on_first_load(qapp):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    view = RadioView(settings)

    try:
        status_item = view.table.item(0, _COL_STATUS)
        assert status_item is not None
        assert status_item.text() == "?"
    finally:
        view.deleteLater()


def test_radio_view_health_cache_restored_after_refresh(qapp, monkeypatch):
    """Health results survive a table refresh (e.g. after adding a station)."""
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._on_health_result("https://jazz.example.test/live", True, 200)

        # Trigger a refresh (e.g. via search clear).
        view.refresh()

        status_item = view.table.item(0, _COL_STATUS)
        assert status_item is not None
        assert "200" in status_item.toolTip()
    finally:
        view.deleteLater()


def test_radio_view_force_health_check_evicts_cache(qapp, monkeypatch):
    """_force_health_check removes the cached result so the next check runs."""
    settings = Settings(
        radio_stations=[
            {"name": "Sea Jazz", "url": "https://jazz.example.test/live"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        # Prime the cache with a healthy result.
        view._on_health_result("https://jazz.example.test/live", True, 200)
        assert "https://jazz.example.test/live" in view._health_cache

        # _force_health_check should evict the cache entry.
        with patch.object(
            radio_view_module.QThreadPool.globalInstance(),
            "start",
        ):
            view._force_health_check("https://jazz.example.test/live")

        assert "https://jazz.example.test/live" not in view._health_cache
        assert "https://jazz.example.test/live" in view._checking
    finally:
        view.deleteLater()


# ---- PR6: Quick-play URL bar ------------------------------------------------

def test_quick_play_valid_url_emits_signal_and_updates_history(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)
    played: list[tuple[str, str]] = []
    view.play_requested.connect(lambda url, title: played.append((url, title)))

    try:
        view._url_input.setText("https://radio.example.test/live")
        view._on_quick_play()

        assert len(played) == 1
        assert played[0][0] == "https://radio.example.test/live"
        assert "https://radio.example.test/live" in settings.radio_quick_play_history
        assert view._qp_error.isHidden()
    finally:
        view.deleteLater()


def test_quick_play_invalid_url_shows_error_no_signal(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)
    played: list = []
    view.play_requested.connect(played.append)

    try:
        view._url_input.setText("not-a-url")
        view._on_quick_play()

        assert played == []
        assert not view._qp_error.isHidden()
        assert settings.radio_quick_play_history == []
    finally:
        view.deleteLater()


def test_quick_play_empty_input_does_nothing(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)
    played: list = []
    view.play_requested.connect(played.append)

    try:
        view._url_input.setText("   ")
        view._on_quick_play()

        assert played == []
        assert view._qp_error.isHidden()
    finally:
        view.deleteLater()


def test_quick_play_shows_toast_for_unsaved_station(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._url_input.setText("https://radio.example.test/live")
        view._on_quick_play()

        assert not view._toast_frame.isHidden()
        assert "radio.example.test" in view._toast_label.text()
    finally:
        view.deleteLater()


def test_quick_play_no_toast_when_station_already_saved(qapp, monkeypatch):
    settings = Settings(
        radio_stations=[
            {"name": "Sea Radio", "url": "https://radio.example.test/live"},
        ]
    )
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._url_input.setText("https://radio.example.test/live")
        view._on_quick_play()

        assert view._toast_frame.isHidden()
    finally:
        view.deleteLater()


def test_quick_play_toast_add_saves_station(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._url_input.setText("https://radio.example.test/live")
        view._on_quick_play()

        assert not view._toast_frame.isHidden()

        view._on_toast_add()

        assert view._toast_frame.isHidden()
        assert any(
            str(raw.get("url", "")) == "https://radio.example.test/live"
            for raw in settings.radio_stations
        )
    finally:
        view.deleteLater()


def test_quick_play_dismiss_hides_toast(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._url_input.setText("https://radio.example.test/live")
        view._on_quick_play()
        assert not view._toast_frame.isHidden()

        view._dismiss_toast()

        assert view._toast_frame.isHidden()
        assert view._toast_station is None
    finally:
        view.deleteLater()


def test_quick_play_history_capped_at_ten(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        for i in range(12):
            settings.add_quick_play_url(f"https://radio{i}.example.test/live")

        assert len(settings.radio_quick_play_history) == 10
        # Most recent is first.
        assert settings.radio_quick_play_history[0] == "https://radio11.example.test/live"
    finally:
        view.deleteLater()


def test_quick_play_deduplicates_history(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)

    settings.add_quick_play_url("https://radio.example.test/live")
    settings.add_quick_play_url("https://other.example.test/live")
    settings.add_quick_play_url("https://radio.example.test/live")  # duplicate

    assert settings.radio_quick_play_history.count("https://radio.example.test/live") == 1
    assert settings.radio_quick_play_history[0] == "https://radio.example.test/live"


def test_quick_play_error_clears_on_new_input(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        view._url_input.setText("bad")
        view._on_quick_play()
        assert not view._qp_error.isHidden()

        view._url_input.setText("https://radio.example.test/live")
        assert view._qp_error.isHidden()
    finally:
        view.deleteLater()


def test_apply_settings_updates_completer_history(qapp, monkeypatch):
    settings = Settings()
    monkeypatch.setattr(settings, "save", lambda: None)
    view = RadioView(settings)

    try:
        new_settings = Settings(
            radio_quick_play_history=["https://a.example.test/live", "https://b.example.test/live"]
        )
        monkeypatch.setattr(new_settings, "save", lambda: None)
        view.apply_settings(new_settings)

        history = view._history_model.stringList()
        assert "https://a.example.test/live" in history
        assert "https://b.example.test/live" in history
    finally:
        view.deleteLater()
