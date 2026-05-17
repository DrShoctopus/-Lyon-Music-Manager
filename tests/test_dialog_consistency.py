"""Phase 6: dialog typography consistency.

Locks in the contract that user-visible dialog labels use named QSS object
names instead of inline setStyleSheet calls. Catches regressions where
someone reintroduces hard-coded colors / font sizes in dialog code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.core.player import Player
from lyon.core.settings import Settings


_DIALOG_MODULES = (
    "lyon/ui/settings_dialog.py",
    "lyon/ui/equalizer_dialog.py",
    "lyon/ui/queue_dialog.py",
    "lyon/ui/first_run_dialog.py",
    "lyon/ui/diagnostics_dialog.py",
    "lyon/ui/yt_download_dialog.py",
)


class _FakeBackend(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    position_changed = QtCore.Signal(int, int)
    end_reached = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self._v, self._m, self._p = 80, False, False

    def set_source(self, _, *, is_location=False, options=()): pass
    def play(self): self._p = True
    def pause(self): self._p = False
    def stop(self): self._p = False
    def position(self): return 0
    def duration(self): return 0
    def set_position(self, _): pass
    def set_volume(self, v): self._v = v
    def volume(self): return self._v
    def set_muted(self, m): self._m = m
    def is_muted(self): return self._m
    def is_playing(self): return self._p
    def apply_equalizer(self, *_a, **_k): pass


@pytest.fixture(scope="module")
def app():
    existing = QtWidgets.QApplication.instance()
    if existing is not None:
        return existing
    return QtWidgets.QApplication([])


@pytest.mark.parametrize("module_path", _DIALOG_MODULES)
def test_no_inline_stylesheets_in_dialog_modules(module_path):
    """Inline setStyleSheet drift is the precise bug Phase 6 set out to fix."""
    src = Path(module_path).read_text()
    # Strip comments before scanning so explanatory prose can't false-positive.
    cleaned = re.sub(r"#.*", "", src)
    assert "setStyleSheet" not in cleaned, (
        f"{module_path} still calls setStyleSheet — use a named QSS class instead."
    )


def test_queue_dialog_summary_uses_named_class(app):
    from lyon.ui.queue_dialog import QueueDialog
    player = Player(backend=_FakeBackend())
    dlg = QueueDialog(player)
    assert dlg.summary.objectName() == "dialogSummary"


def test_diagnostics_dialog_summary_uses_named_class(app):
    from lyon.ui.diagnostics_dialog import DiagnosticsDialog
    dlg = DiagnosticsDialog()
    summaries = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "dialogSummary"
    ]
    assert len(summaries) == 1


def test_first_run_dialog_title_and_form_labels_are_named(app):
    from lyon.ui.first_run_dialog import FirstRunDialog
    dlg = FirstRunDialog(Settings.load())
    titles = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "sectionTitle"
    ]
    form_labels = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "formLabel"
    ]
    assert len(titles) >= 1
    assert len(form_labels) == 2  # music root + library folders


def test_settings_about_tab_uses_dialog_typography_classes(app):
    from lyon.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings.load())
    titles = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "dialogTitle"
    ]
    subtitles = [
        lbl for lbl in dlg.findChildren(QtWidgets.QLabel)
        if lbl.objectName() == "dialogSubtitle"
    ]
    assert len(titles) == 1
    assert len(subtitles) == 1


def test_yt_download_dialog_log_is_monospace(app):
    # We don't fully construct this dialog (it kicks off a worker thread on
    # show), but we do verify the symbol exists and the class is intact.
    import lyon.ui.yt_download_dialog as mod
    src = Path(mod.__file__).read_text()
    assert 'setObjectName("monoLog")' in src
    assert 'setObjectName("sectionHeading")' in src
