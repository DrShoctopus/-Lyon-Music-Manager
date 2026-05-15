from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.equalizer import BUILTIN_EQ_CURVES, UNSAVED_EQ_CURVE_NAME
from lyon.core.settings import Settings
from lyon.ui.equalizer_dialog import EqualizerDialog


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


def test_selecting_builtin_curve_applies_bands_once(app):
    dialog = EqualizerDialog(Settings(), None)
    changes: list[tuple[bool, list[int], int]] = []
    dialog.equalizer_changed.connect(lambda enabled, bands, preamp: changes.append((enabled, list(bands), preamp)))

    rock_index = dialog.curve_combo.findText("Rock")
    dialog.curve_combo.setCurrentIndex(rock_index)

    assert dialog.band_values() == BUILTIN_EQ_CURVES["Rock"]
    assert dialog.result_settings.equalizer_curve_name == "Rock"
    assert changes == [(False, BUILTIN_EQ_CURVES["Rock"], 0)]


def test_manual_slider_edit_marks_dropdown_as_unsaved(app):
    dialog = EqualizerDialog(Settings(equalizer_curve_name="Rock"), None)

    dialog._sliders[0].setValue(3)

    assert dialog.result_settings.equalizer_curve_name == UNSAVED_EQ_CURVE_NAME
    assert dialog.curve_combo.currentText() == UNSAVED_EQ_CURVE_NAME


def test_preamp_slider_initializes_from_settings(app):
    dialog = EqualizerDialog(Settings(equalizer_preamp=8), None)

    assert dialog.preamp_value() == 8
    assert dialog.result_settings.equalizer_preamp == 0  # not synced until _emit_change
    dialog._emit_change()
    assert dialog.result_settings.equalizer_preamp == 8


def test_reset_flat_resets_preamp_and_emits_once(app):
    dialog = EqualizerDialog(Settings(equalizer_preamp=10, equalizer_enabled=True), None)
    emissions: list[tuple[bool, list[int], int]] = []
    dialog.equalizer_changed.connect(lambda e, b, p: emissions.append((e, b, p)))

    dialog.reset_flat()

    assert dialog.preamp_value() == 0
    assert dialog.enable_box.isChecked() is False
    assert len(emissions) == 1
    assert emissions[0] == (False, [0] * 10, 0)


def test_saving_reserved_builtin_name_creates_selectable_custom_curve(app, monkeypatch):
    dialog = EqualizerDialog(Settings(), None)
    dialog._sliders[0].setValue(7)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *args, **kwargs: ("Rock", True))

    dialog.save_current_curve_as()

    assert dialog.result_settings.equalizer_curve_name == "Rock (Custom)"
    assert dialog.result_settings.equalizer_custom_curves["Rock (Custom)"][0] == 7
    assert dialog.curve_combo.currentData() == ("custom", "Rock (Custom)")
