"""Podcast subscription and episode browser."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.podcast import (
    PodcastEpisode,
    PodcastFeed,
    PodcastSubscription,
    fetch_feed,
    parse_opml_file,
    subscription_from_settings,
)
from ..core.settings import Settings, normalize_podcast_subscriptions

LOG = logging.getLogger(__name__)

_COL_SHOW = 0
_COL_EPISODE = 1
_COL_DURATION = 2
_COL_PUBLISHED = 3
_COL_URL = 4


class _PodcastDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Podcast")
        self.resize(460, 130)

        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/feed.xml")
        self.url_edit.setClearButtonEnabled(True)
        form.addRow("Feed URL:", self.url_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def url(self) -> str:
        return self.url_edit.text().strip()


class _PodcastRefreshThread(QThread):
    finished_with = Signal(list, list, list)  # feeds, episodes, errors

    def __init__(self, subscriptions: list[PodcastSubscription], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._subscriptions = list(subscriptions)

    def run(self) -> None:
        feeds: list[PodcastFeed] = []
        episodes: list[PodcastEpisode] = []
        errors: list[str] = []
        for subscription in self._subscriptions:
            if self.isInterruptionRequested():
                break
            try:
                feed = fetch_feed(subscription.url)
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                LOG.warning("Could not refresh podcast feed %s: %s", subscription.url, exc)
                errors.append(f"{subscription.title}: {exc}")
                continue
            feeds.append(feed)
            episodes.extend(feed.episodes)
        self.finished_with.emit(feeds, episodes, errors)


class PodcastView(QWidget):
    play_requested = Signal(str, str)  # url, title
    status_message = Signal(str)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._episodes: list[PodcastEpisode] = []
        self._refresh_thread: _PodcastRefreshThread | None = None
        self.setObjectName("podcastView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search podcasts...")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Podcast episode search")
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search, 1)

        self.play_btn = QPushButton("Play")
        self.play_btn.setObjectName("accent")
        self.play_btn.clicked.connect(self._play_selected)
        toolbar.addWidget(self.play_btn)

        self.add_btn = QPushButton("Add...")
        self.add_btn.clicked.connect(self._add_podcast)
        toolbar.addWidget(self.add_btn)

        self.import_btn = QPushButton("Import OPML...")
        self.import_btn.clicked.connect(self._import_opml)
        toolbar.addWidget(self.import_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_btn)

        self.remove_btn = QPushButton("Remove Feed")
        self.remove_btn.clicked.connect(self._remove_selected_feed)
        toolbar.addWidget(self.remove_btn)

        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("podcastEpisodeTable")
        self.table.setHorizontalHeaderLabels(["Show", "Episode", "Duration", "Published", "URL"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda _item: self._play_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_SHOW, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_EPISODE, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_DURATION, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PUBLISHED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_URL, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("podcastFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_label = QLabel("")
        self.footer_label.setObjectName("mutedText")
        footer_layout.addWidget(self.footer_label)
        footer_layout.addStretch(1)
        layout.addWidget(footer)

        self._filter("")
        self._update_buttons()

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._episodes = []
        self._populate_table()

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        """Stop the refresh worker before the widget/app is destroyed."""
        thread = self._refresh_thread
        if thread is None or not thread.isRunning():
            return True
        thread.requestInterruption()
        if not thread.wait(timeout_ms):
            return False
        if self._refresh_thread is thread:
            thread.deleteLater()
            self._refresh_thread = None
        return True

    def refresh(self) -> None:
        subscriptions = self._subscriptions()
        if not subscriptions:
            self._episodes = []
            self._populate_table()
            self.status_message.emit("Add a podcast feed or import OPML to get started.")
            return
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            self.status_message.emit("Podcast refresh already in progress.")
            return
        self.refresh_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.import_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.footer_label.setText("Refreshing podcasts...")
        self._refresh_thread = _PodcastRefreshThread(subscriptions, self)
        self._refresh_thread.finished_with.connect(self._on_refresh_finished)
        self._refresh_thread.finished.connect(self._on_refresh_thread_finished)
        self._refresh_thread.start()

    def _append_episode_row(self, episode: PodcastEpisode) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        show_item = QTableWidgetItem(episode.feed_title)
        show_item.setData(Qt.UserRole, episode)
        self.table.setItem(row, _COL_SHOW, show_item)
        self.table.setItem(row, _COL_EPISODE, QTableWidgetItem(episode.title))
        self.table.setItem(row, _COL_DURATION, QTableWidgetItem(episode.duration))
        self.table.setItem(row, _COL_PUBLISHED, QTableWidgetItem(episode.published))
        self.table.setItem(row, _COL_URL, QTableWidgetItem(episode.url))

    def _current_episode(self) -> PodcastEpisode | None:
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return None
        item = self.table.item(row, _COL_SHOW)
        if item is None:
            return None
        episode = item.data(Qt.UserRole)
        return episode if isinstance(episode, PodcastEpisode) else None

    def _play_selected(self) -> None:
        episode = self._current_episode()
        if episode is None:
            return
        title = f"{episode.feed_title} - {episode.title}" if episode.feed_title else episode.title
        self._settings.remember_stream_url(episode.url)
        self._save_settings()
        self.play_requested.emit(episode.url, title)

    def _add_podcast(self) -> None:
        dialog = _PodcastDialog(self)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            url = dialog.url()
        finally:
            dialog.deleteLater()
        if not url:
            return
        try:
            feed = fetch_feed(url)
        except Exception as exc:
            LOG.warning("Could not add podcast %s: %s", url, exc)
            QMessageBox.warning(self, "Add Podcast", f"Could not read podcast feed.\n{exc}")
            return
        self._settings.add_podcast_subscriptions([feed.subscription().as_settings_dict()])
        self._save_settings()
        self._apply_refresh_results([feed], [*self._episodes, *feed.episodes], [])
        self.status_message.emit(f'Added podcast "{feed.title}".')

    def _import_opml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Podcast OPML",
            "",
            "OPML Files (*.opml *.xml);;All Files (*)",
        )
        if not path:
            return
        try:
            subscriptions = parse_opml_file(path)
        except (OSError, ValueError) as exc:
            LOG.warning("Could not import OPML %s: %s", path, exc)
            QMessageBox.warning(self, "Import Podcast OPML", f"Could not read {Path(path).name}.")
            return
        if not subscriptions:
            QMessageBox.warning(self, "Import Podcast OPML", "No podcast feed URLs were found.")
            return
        self._settings.add_podcast_subscriptions([
            subscription.as_settings_dict()
            for subscription in subscriptions
        ])
        self._save_settings()
        count = len(subscriptions)
        self.status_message.emit(f"Imported {count} podcast feed{'' if count == 1 else 's'}.")
        self.refresh()

    def _remove_selected_feed(self) -> None:
        episode = self._current_episode()
        if episode is None:
            return
        feed_url = episode.feed_url.casefold()
        feed_title = episode.feed_title.casefold()
        if feed_url:
            remaining = [
                raw
                for raw in self._settings.podcast_subscriptions
                if str(raw.get("url", "")).casefold() != feed_url
            ]
        else:
            remaining = [
                raw
                for raw in self._settings.podcast_subscriptions
                if str(raw.get("title", "")).casefold() != feed_title
            ]
        self._settings.podcast_subscriptions = normalize_podcast_subscriptions(remaining)
        if feed_url:
            self._episodes = [
                item
                for item in self._episodes
                if item.feed_url.casefold() != feed_url
            ]
        else:
            self._episodes = [
                item
                for item in self._episodes
                if item.feed_title.casefold() != feed_title
            ]
        self._save_settings()
        self._populate_table()
        self.status_message.emit(f'Removed podcast "{episode.feed_title}".')

    def _on_refresh_finished(
        self,
        feeds: list[PodcastFeed],
        episodes: list[PodcastEpisode],
        errors: list[str],
    ) -> None:
        self._apply_refresh_results(feeds, episodes, errors)

    def _on_refresh_thread_finished(self) -> None:
        if self._refresh_thread is not None:
            self._refresh_thread.deleteLater()
            self._refresh_thread = None
        self.refresh_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.import_btn.setEnabled(True)
        self._update_buttons()

    def _apply_refresh_results(
        self,
        feeds: list[PodcastFeed],
        episodes: list[PodcastEpisode],
        errors: list[str],
    ) -> None:
        active_urls = {
            str(raw.get("url", "")).casefold()
            for raw in self._settings.podcast_subscriptions
            if isinstance(raw, dict)
        }
        feeds = [
            feed
            for feed in feeds
            if not feed.url or feed.url.casefold() in active_urls
        ]
        episodes = [
            episode
            for episode in episodes
            if not episode.feed_url or episode.feed_url.casefold() in active_urls
        ]
        if feeds:
            self._settings.add_podcast_subscriptions([
                feed.subscription().as_settings_dict()
                for feed in feeds
                if feed.url
            ])
            self._save_settings()
        self._episodes = sorted(
            episodes,
            key=lambda episode: (episode.published, episode.feed_title, episode.title),
            reverse=True,
        )
        self._populate_table()
        if errors and episodes:
            self.status_message.emit(f"Refreshed podcasts with {len(errors)} feed error{'' if len(errors) == 1 else 's'}.")
        elif errors:
            self.status_message.emit(f"Podcast refresh failed for {len(errors)} feed{'' if len(errors) == 1 else 's'}.")
        else:
            self.status_message.emit(f"Refreshed {len(episodes)} podcast episode{'' if len(episodes) == 1 else 's'}.")

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for episode in self._episodes:
            self._append_episode_row(episode)
        self._filter(self.search.text())
        self._update_buttons()

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            _item = self.table.item(row, _COL_SHOW)
            episode = _item.data(Qt.UserRole) if _item is not None else None
            haystack = " ".join((
                episode.feed_title,
                episode.title,
                episode.description,
                episode.published,
                episode.url,
            )).casefold() if isinstance(episode, PodcastEpisode) else ""
            show = not query or query in haystack
            self.table.setRowHidden(row, not show)
            if show:
                visible += 1
        total = self.table.rowCount()
        if total:
            self.footer_label.setText(f"{visible}/{total} episodes" if query else f"{total} episodes")
        else:
            count = len(self._settings.podcast_subscriptions)
            self.footer_label.setText(f"{count} subscribed feed{'' if count == 1 else 's'}")
        self._update_buttons()

    def _subscriptions(self) -> list[PodcastSubscription]:
        subscriptions: list[PodcastSubscription] = []
        for raw in self._settings.podcast_subscriptions:
            subscription = subscription_from_settings(raw)
            if subscription is not None:
                subscriptions.append(subscription)
        return subscriptions

    def _save_settings(self) -> None:
        self._settings.save()

    def _update_buttons(self) -> None:
        refreshing = self._refresh_thread is not None and self._refresh_thread.isRunning()
        selected = self._current_episode() is not None
        self.play_btn.setEnabled(selected)
        self.remove_btn.setEnabled(selected and not refreshing)
