"""Phase 8: WMP_QSS validity + cross-reference with object names used in code.

Goals:
1. The central stylesheet parses without Qt emitting "Could not parse
   stylesheet" warnings — caught by routing qInstallMessageHandler.
2. Every #objectName rule in the QSS has at least one matching
   setObjectName call somewhere in lyon/ui, preventing dead QSS rules
   from accumulating.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from lyon.ui.styles import WMP_QSS


def test_qss_parses_without_warnings(qapp):
    """Applying the stylesheet must not produce Qt parser warnings."""
    warnings: list[str] = []

    def handler(_msg_type, _ctx, message):
        if "stylesheet" in message.lower() or "could not parse" in message.lower():
            warnings.append(str(message))

    original = QtCore.qInstallMessageHandler(handler)
    try:
        widget = QtWidgets.QWidget()
        widget.setStyleSheet(WMP_QSS)
        widget.deleteLater()
    finally:
        QtCore.qInstallMessageHandler(original)

    assert not warnings, "QSS parser produced warnings:\n" + "\n".join(warnings)


# 3- or 6-digit hex color literal — matches "#abc", "#a1b2c3".
_HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")


def _qss_object_name_selectors() -> set[str]:
    """Extract every #objectName referenced in WMP_QSS, excluding hex colors."""
    raw = re.findall(r"#([A-Za-z_][A-Za-z0-9_]*)", WMP_QSS)
    return {name for name in raw if not _HEX_COLOR_RE.match(name)}


def _setobjectname_values_in_ui_tree() -> set[str]:
    """Scan every Python source under lyon/ui for setObjectName("X") literals."""
    used: set[str] = set()
    for path in Path("lyon/ui").glob("*.py"):
        src = path.read_text()
        # Capture `setObjectName("value")` and `setObjectName('value')`.
        for m in re.finditer(r'setObjectName\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']\s*\)', src):
            used.add(m.group(1))
    return used


# Some object names are set dynamically via setProperty() or by Qt itself
# (e.g. the "root" widget). List those exceptions explicitly.
_KNOWN_DYNAMIC_OBJECT_NAMES = {
    # Set in main_window.py via setObjectName("root") on the central widget.
    "root",
}


def test_every_qss_object_name_is_used_in_code():
    declared_in_qss = _qss_object_name_selectors()
    set_in_code = _setobjectname_values_in_ui_tree() | _KNOWN_DYNAMIC_OBJECT_NAMES
    orphans = declared_in_qss - set_in_code
    assert not orphans, (
        "QSS contains rules for object names that are never set in code "
        f"(dead styling): {sorted(orphans)}"
    )
