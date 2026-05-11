"""Six-band equalizer window."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import Settings


EQ_BANDS: tuple[tuple[str, str], ...] = (
    ("60 Hz", "Sub bass"),
    ("150 Hz", "Bass"),
    ("400 Hz", "Low mids"),
    ("1 kHz", "Mids"),
    ("3 kHz", "Presence"),
    ("10 kHz", "Brilliance"),
)

MIN_GAIN_DB = -12
MAX_GAIN_DB = 12


class EqualizerDialog(QDialog):
    """Non-modal six-band equalizer editor.

    The dialog owns an editable copy of Settings and emits every change so the
    player can react immediately while the user moves each band.
    """

    equalizer_changed = Signal(bool, list)
    settings_saved = Signal(object)

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("6 Band Equalizer")
        self.setModal(False)
        self.resize(560, 360)
        self.result_settings = replace(settings)
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QLabel("6 Band Equalizer")
        header.setObjectName("sectionTitle")
        layout.addWidget(header)

        self.enable_box = QCheckBox("Enable equalizer")
        self.enable_box.setChecked(settings.equalizer_enabled)
        self.enable_box.toggled.connect(self._emit_change)
        layout.addWidget(self.enable_box)

        panel = QFrame()
        panel.setObjectName("equalizerPanel")
        grid = QGridLayout(panel)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setContentsMargins(14, 12, 14, 12)

        values = self._normalized_bands(settings.equalizer_bands)
        for col, ((band, tooltip), value) in enumerate(zip(EQ_BANDS, values, strict=True)):
            slider = QSlider(Qt.Vertical)
            slider.setRange(MIN_GAIN_DB, MAX_GAIN_DB)
            slider.setValue(value)
            slider.setTickPosition(QSlider.TicksBothSides)
            slider.setTickInterval(6)
            slider.setToolTip(f"{band} - {tooltip}")
            slider.valueChanged.connect(self._update_value_labels)
            slider.valueChanged.connect(self._emit_change)

            value_label = QLabel(self._format_gain(value))
            value_label.setAlignment(Qt.AlignCenter)
            band_label = QLabel(band)
            band_label.setAlignment(Qt.AlignCenter)
            band_label.setToolTip(tooltip)

            self._sliders.append(slider)
            self._value_labels.append(value_label)
            grid.addWidget(value_label, 0, col)
            grid.addWidget(slider, 1, col, alignment=Qt.AlignHCenter)
            grid.addWidget(band_label, 2, col)

        layout.addWidget(panel, 1)

        hint = QLabel("Adjust each band from -12 dB to +12 dB. Changes apply immediately and are saved with the app settings.")
        hint.setWordWrap(True)
        hint.setObjectName("mutedText")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        reset = QPushButton("Reset Flat")
        reset.clicked.connect(self.reset_flat)
        save = QPushButton("Save")
        save.setObjectName("accent")
        save.clicked.connect(self.save_settings)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(reset)
        buttons.addWidget(save)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def reset_flat(self) -> None:
        self.enable_box.setChecked(False)
        for slider in self._sliders:
            slider.setValue(0)
        self._emit_change()

    def save_settings(self) -> None:
        self._sync_result_settings()
        self.result_settings.save()
        self.settings_saved.emit(self.result_settings)

    def closeEvent(self, event) -> None:
        self.save_settings()
        super().closeEvent(event)

    def _sync_result_settings(self) -> None:
        self.result_settings.equalizer_enabled = self.enable_box.isChecked()
        self.result_settings.equalizer_bands = self.band_values()

    def band_values(self) -> list[int]:
        return [slider.value() for slider in self._sliders]

    def _update_value_labels(self) -> None:
        for slider, label in zip(self._sliders, self._value_labels, strict=True):
            label.setText(self._format_gain(slider.value()))

    def _emit_change(self) -> None:
        self._sync_result_settings()
        self.equalizer_changed.emit(self.result_settings.equalizer_enabled, self.band_values())

    @staticmethod
    def _format_gain(value: int) -> str:
        return f"{value:+d} dB"

    @staticmethod
    def _normalized_bands(values: list[int]) -> list[int]:
        normalized = list(values[: len(EQ_BANDS)])
        normalized.extend([0] * (len(EQ_BANDS) - len(normalized)))
        return [max(MIN_GAIN_DB, min(MAX_GAIN_DB, int(value))) for value in normalized]
