"""Ten-band equalizer window with preset and custom curve support."""
from __future__ import annotations

from dataclasses import replace
from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.equalizer import (
    BUILTIN_EQ_CURVES,
    DEFAULT_EQ_CURVE_NAME,
    DEFAULT_EQ_PREAMP_DB,
    EQ_BANDS,
    MAX_EQ_GAIN_DB,
    MAX_EQ_PREAMP_DB,
    MIN_EQ_GAIN_DB,
    MIN_EQ_PREAMP_DB,
    RESERVED_EQ_CURVE_NAMES,
    UNSAVED_EQ_CURVE_NAME,
    flat_equalizer_bands,
    normalize_equalizer_bands,
)
from ..core.settings import Settings

CurveType = Literal["builtin", "custom", "unsaved"]
CurveData = tuple[CurveType, str]


class EqualizerDialog(QDialog):
    """Non-modal ten-band equalizer editor.

    The dialog owns an editable copy of Settings and emits every change so the
    libVLC-backed player can react immediately while the user moves each band.
    Curves can be selected from five built-in presets or saved as user-named
    custom presets in the same picker.
    """

    equalizer_changed = Signal(bool, list, int)
    settings_saved = Signal(object)

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("10 Band Equalizer")
        self.setModal(False)
        self.resize(760, 440)
        self.result_settings = replace(
            settings,
            equalizer_bands=normalize_equalizer_bands(settings.equalizer_bands),
            equalizer_custom_curves={
                name: normalize_equalizer_bands(curve)
                for name, curve in settings.equalizer_custom_curves.items()
                if name not in RESERVED_EQ_CURVE_NAMES
            },
        )
        self._sliders: list[QSlider] = []
        self._value_labels: list[QLabel] = []
        self._loading_curve = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QLabel("10 Band Equalizer")
        header.setObjectName("sectionTitle")
        layout.addWidget(header)

        top_row = QHBoxLayout()
        self.enable_box = QCheckBox("Enable equalizer")
        self.enable_box.setChecked(settings.equalizer_enabled)
        self.enable_box.toggled.connect(self._emit_change)
        top_row.addWidget(self.enable_box)
        top_row.addStretch(1)
        top_row.addWidget(QLabel("Curve:"))
        self.curve_combo = QComboBox()
        self.curve_combo.setMinimumWidth(220)
        self._populate_curve_combo(settings.equalizer_curve_name)
        self.curve_combo.currentIndexChanged.connect(self._curve_selected)
        top_row.addWidget(self.curve_combo)
        save_curve = QPushButton("Save Current As...")
        save_curve.clicked.connect(self.save_current_curve_as)
        delete_curve = QPushButton("Delete Custom")
        delete_curve.clicked.connect(self.delete_selected_custom_curve)
        top_row.addWidget(save_curve)
        top_row.addWidget(delete_curve)
        layout.addLayout(top_row)

        preamp_row = QHBoxLayout()
        preamp_row.addWidget(QLabel("Preamp:"))
        self._preamp_slider = QSlider(Qt.Horizontal)
        self._preamp_slider.setRange(MIN_EQ_PREAMP_DB, MAX_EQ_PREAMP_DB)
        self._preamp_slider.setValue(settings.equalizer_preamp)
        self._preamp_slider.setTickPosition(QSlider.TicksBothSides)
        self._preamp_slider.setTickInterval(5)
        self._preamp_slider.setToolTip("Overall gain applied before the EQ bands")
        self._preamp_slider.valueChanged.connect(self._preamp_changed)
        preamp_row.addWidget(self._preamp_slider, 1)
        self._preamp_label = QLabel(self._format_gain(settings.equalizer_preamp))
        self._preamp_label.setMinimumWidth(54)
        self._preamp_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        preamp_row.addWidget(self._preamp_label)
        layout.addLayout(preamp_row)

        panel = QFrame()
        panel.setObjectName("equalizerPanel")
        grid = QGridLayout(panel)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setContentsMargins(14, 12, 14, 12)

        values = normalize_equalizer_bands(settings.equalizer_bands)
        for col, ((band, tooltip), value) in enumerate(zip(EQ_BANDS, values, strict=True)):
            slider = QSlider(Qt.Vertical)
            slider.setRange(MIN_EQ_GAIN_DB, MAX_EQ_GAIN_DB)
            slider.setValue(value)
            slider.setTickPosition(QSlider.TicksBothSides)
            slider.setTickInterval(6)
            slider.setToolTip(f"{band} - {tooltip}")
            slider.valueChanged.connect(self._slider_changed)

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

        hint = QLabel(
            "Preamp adjusts the overall input level before the EQ bands are applied. "
            "Lyon maps the ten band controls directly to libVLC's native EQ. "
            "Changes apply immediately and are saved with the app settings."
        )
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
        self.enable_box.blockSignals(True)
        self.enable_box.setChecked(False)
        self.enable_box.blockSignals(False)
        self._preamp_slider.blockSignals(True)
        self._preamp_slider.setValue(DEFAULT_EQ_PREAMP_DB)
        self._preamp_slider.blockSignals(False)
        self._preamp_label.setText(self._format_gain(DEFAULT_EQ_PREAMP_DB))
        self.result_settings.equalizer_curve_name = DEFAULT_EQ_CURVE_NAME
        self._select_curve(DEFAULT_EQ_CURVE_NAME, curve_type="builtin")
        self._set_sliders(flat_equalizer_bands())
        self._emit_change()

    def save_current_curve_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Equalizer Curve", "Curve name:")
        if not ok:
            return
        name = self._custom_curve_name(name)
        if not name:
            return
        self.result_settings.equalizer_custom_curves[name] = self.band_values()
        self.result_settings.equalizer_curve_name = name
        self._populate_curve_combo(name, curve_type="custom")
        self._emit_change()

    def delete_selected_custom_curve(self) -> None:
        curve_type, name = self._current_curve_data()
        if curve_type != "custom":
            return
        self.result_settings.equalizer_custom_curves.pop(name, None)
        self.result_settings.equalizer_curve_name = DEFAULT_EQ_CURVE_NAME
        self._populate_curve_combo(DEFAULT_EQ_CURVE_NAME, curve_type="builtin")
        self._set_sliders(flat_equalizer_bands())
        self._emit_change()

    def save_settings(self) -> None:
        self._sync_result_settings()
        self.result_settings.save()
        self.settings_saved.emit(self.result_settings)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)

    def _populate_curve_combo(
        self,
        selected_name: str,
        *,
        curve_type: CurveType | None = None,
    ) -> None:
        self.curve_combo.blockSignals(True)
        self.curve_combo.clear()
        if selected_name == UNSAVED_EQ_CURVE_NAME:
            self.curve_combo.addItem(UNSAVED_EQ_CURVE_NAME, ("unsaved", UNSAVED_EQ_CURVE_NAME))
        self.curve_combo.addItem(DEFAULT_EQ_CURVE_NAME, ("builtin", DEFAULT_EQ_CURVE_NAME))
        for name in BUILTIN_EQ_CURVES:
            self.curve_combo.addItem(name, ("builtin", name))
        if self.result_settings.equalizer_custom_curves:
            self.curve_combo.insertSeparator(self.curve_combo.count())
            for name in sorted(self.result_settings.equalizer_custom_curves):
                self.curve_combo.addItem(name, ("custom", name))
        self._select_curve(selected_name, curve_type=curve_type)
        self.curve_combo.blockSignals(False)

    def _select_curve(self, name: str, *, curve_type: CurveType | None = None) -> None:
        for index in range(self.curve_combo.count()):
            data = self.curve_combo.itemData(index)
            if not data:
                continue
            if data[1] == name and (curve_type is None or data[0] == curve_type):
                self.curve_combo.setCurrentIndex(index)
                return
        self.curve_combo.setCurrentIndex(0)

    def _curve_selected(self) -> None:
        curve_type, name = self._current_curve_data()
        if curve_type == "custom":
            bands = self.result_settings.equalizer_custom_curves.get(name, flat_equalizer_bands())
        elif name in BUILTIN_EQ_CURVES:
            bands = BUILTIN_EQ_CURVES[name]
        else:
            bands = flat_equalizer_bands()
        self.result_settings.equalizer_curve_name = name
        self._set_sliders(bands)
        self._emit_change()

    def _current_curve_data(self) -> CurveData:
        data = self.curve_combo.currentData()
        if data is None:
            return "builtin", DEFAULT_EQ_CURVE_NAME
        return data

    def _sync_result_settings(self) -> None:
        self.result_settings.equalizer_enabled = self.enable_box.isChecked()
        self.result_settings.equalizer_preamp = self.preamp_value()
        self.result_settings.equalizer_bands = self.band_values()

    def preamp_value(self) -> int:
        return self._preamp_slider.value()

    def band_values(self) -> list[int]:
        return [slider.value() for slider in self._sliders]

    def _set_sliders(self, bands: list[int]) -> None:
        self._loading_curve = True
        for slider, value in zip(self._sliders, normalize_equalizer_bands(bands), strict=True):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self._loading_curve = False
        self._update_value_labels()

    def _slider_changed(self) -> None:
        self._update_value_labels()
        if not self._loading_curve:
            self._mark_unsaved_curve()
        self._emit_change()

    def _mark_unsaved_curve(self) -> None:
        self.result_settings.equalizer_curve_name = UNSAVED_EQ_CURVE_NAME
        if self.curve_combo.currentData() == ("unsaved", UNSAVED_EQ_CURVE_NAME):
            return
        self._populate_curve_combo(UNSAVED_EQ_CURVE_NAME, curve_type="unsaved")

    def _custom_curve_name(self, raw_name: str) -> str:
        name = raw_name.strip()
        if not name:
            return ""
        if name in RESERVED_EQ_CURVE_NAMES:
            name = f"{name} (Custom)"
        return name

    def _update_value_labels(self) -> None:
        for slider, label in zip(self._sliders, self._value_labels, strict=True):
            label.setText(self._format_gain(slider.value()))

    def _preamp_changed(self) -> None:
        self._preamp_label.setText(self._format_gain(self._preamp_slider.value()))
        self._emit_change()

    def _emit_change(self) -> None:
        self._sync_result_settings()
        self.equalizer_changed.emit(self.result_settings.equalizer_enabled, self.band_values(), self.preamp_value())

    @staticmethod
    def _format_gain(value: int) -> str:
        return f"{value:+d} dB"
