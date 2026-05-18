from __future__ import annotations

import pytest


def test_main_opens_main_window_maximized(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

    from lyon import app as app_mod

    calls: list[str] = []

    class FakeApplication:
        def __init__(self, _argv):
            calls.append("app-init")

        @staticmethod
        def setHighDpiScaleFactorRoundingPolicy(_policy):
            calls.append("dpi-policy")

        def setApplicationName(self, _name):
            calls.append("app-name")

        def setOrganizationName(self, _name):
            calls.append("org-name")

        def setFont(self, _font):
            calls.append("font")

        def setWindowIcon(self, _icon):
            calls.append("app-icon")

        def exec(self):
            calls.append("exec")
            return 0

    class FakeMainWindow:
        def __init__(self):
            calls.append("window-init")

        def setWindowIcon(self, _icon):
            calls.append("window-icon")

        def show(self):
            calls.append("show")

        def showMaximized(self):
            calls.append("show-maximized")

    monkeypatch.setattr(app_mod, "QApplication", FakeApplication)
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindow)
    monkeypatch.setattr(app_mod, "app_icon", lambda: object())
    monkeypatch.setattr(app_mod, "create_startup_splash", lambda _app: calls.append("splash"))
    monkeypatch.setattr(
        app_mod,
        "finish_startup_splash",
        lambda _app, _win: calls.append("finish-splash"),
    )

    assert app_mod.main() == 0
    assert "show-maximized" in calls
    assert "show" not in calls
    assert calls.index("show-maximized") < calls.index("finish-splash")
