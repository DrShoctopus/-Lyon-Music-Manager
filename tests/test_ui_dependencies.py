"""Guard against silently skipping the Qt UI suite.

Most widget tests import PySide6 at module scope. If the dependency is missing,
pytest reports those modules as skipped and can make a UI push look green while
zero UI assertions actually ran. This explicit dependency check fails loudly in
that environment.
"""
from __future__ import annotations

import importlib.util


def test_pyside6_is_available_for_ui_tests():
    assert importlib.util.find_spec("PySide6") is not None, (
        "PySide6 is required for the UI test suite. Install project "
        "requirements before accepting UI/UX changes."
    )
