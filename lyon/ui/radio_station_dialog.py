"""Dialog for adding and editing radio stations."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.radio import RadioStation, station_from_url


class RadioStationDialog(QDialog):
    """Add or edit a radio station.

    Pass an existing *station* to pre-fill all fields (edit mode).
    Call ``station()`` after ``exec()`` returns ``Accepted`` to retrieve
    the validated result.
    """

    def __init__(
        self,
        station: RadioStation | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Radio Station" if station else "Add Radio Station")
        self.resize(460, 230)

        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 4)
        form.setVerticalSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Station name")
        form.addRow("Name:", self.name_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/stream")
        form.addRow("URL:", self.url_edit)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Optional")
        form.addRow("Genre:", self.genre_edit)

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Comma-separated, e.g. jazz, smooth, 90s")
        form.addRow("Tags:", self.tags_edit)

        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(0, 9999)
        self.bitrate_spin.setSuffix(" kbps")
        self.bitrate_spin.setSpecialValueText("Unknown")
        form.addRow("Bitrate:", self.bitrate_spin)

        self._error_label = QLabel()
        self._error_label.setObjectName("errorText")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        self._save_btn = buttons.button(QDialogButtonBox.Save)
        self._save_btn.clicked.connect(self._on_save)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error_label)
        layout.addWidget(buttons)

        self._result: RadioStation | None = None
        self._original_favorite: bool = False

        if station is not None:
            self.name_edit.setText(station.name)
            self.url_edit.setText(station.url)
            self.genre_edit.setText(station.genre)
            self.tags_edit.setText(", ".join(station.tags))
            self.bitrate_spin.setValue(station.bitrate)
            self._original_favorite = station.favorite

        self.url_edit.textChanged.connect(lambda _: self._error_label.setVisible(False))

    def station(self) -> RadioStation | None:
        return self._result

    def _on_save(self) -> None:
        url = self.url_edit.text().strip()
        name = self.name_edit.text().strip()
        genre = self.genre_edit.text().strip()
        bitrate = self.bitrate_spin.value()
        tags_raw = self.tags_edit.text()
        tags: tuple[str, ...] = tuple(
            t.strip() for t in tags_raw.split(",") if t.strip()
        )

        result = station_from_url(
            url,
            name=name,
            genre=genre,
            bitrate=bitrate,
            tags=tags,
            favorite=self._original_favorite,
        )
        if result is None:
            self._error_label.setText(
                "Enter a valid stream URL (must begin with http:// or https://)."
            )
            self._error_label.setVisible(True)
            self.url_edit.setFocus()
            return

        self._result = result
        self.accept()
