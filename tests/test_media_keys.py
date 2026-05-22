from __future__ import annotations

from lyon.core import media_keys


class _FakePlayer:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self.fail:
            raise RuntimeError("boom")

    def toggle(self) -> None:
        self._record("toggle")

    def next(self) -> None:
        self._record("next")

    def previous(self) -> None:
        self._record("previous")

    def stop(self) -> None:
        self._record("stop")


def test_windows_appcommand_is_extracted_from_lparam_high_word():
    assert media_keys._command_from_lparam(14 << 16) == 14
    assert media_keys._command_from_lparam((14 << 16) | 0x1234) == 14


def test_windows_appcommands_route_to_player_controls():
    player = _FakePlayer()

    assert media_keys._dispatch_app_command(player, media_keys._APPCOMMAND_MEDIA_PLAY_PAUSE)
    assert media_keys._dispatch_app_command(player, media_keys._APPCOMMAND_MEDIA_NEXTTRACK)
    assert media_keys._dispatch_app_command(player, media_keys._APPCOMMAND_MEDIA_PREVIOUSTRACK)
    assert media_keys._dispatch_app_command(player, media_keys._APPCOMMAND_MEDIA_STOP)

    assert player.calls == ["toggle", "next", "previous", "stop"]


def test_unknown_windows_appcommand_is_ignored():
    player = _FakePlayer()

    assert not media_keys._dispatch_app_command(player, 999)

    assert player.calls == []


def test_windows_appcommand_handler_swallows_player_errors():
    player = _FakePlayer(fail=True)

    assert media_keys._dispatch_app_command(player, media_keys._APPCOMMAND_MEDIA_PLAY_PAUSE)

    assert player.calls == ["toggle"]


def test_register_media_key_handler_noops_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(media_keys.sys, "platform", "linux")

    assert media_keys.register_media_key_handler(_FakePlayer()) is None


def test_register_media_key_handler_returns_installed_windows_handler(monkeypatch):
    installed: list[object] = []

    class FakeHandler:
        def __init__(self, player: object) -> None:
            self.player = player

        def install(self) -> bool:
            installed.append(self)
            return True

    monkeypatch.setattr(media_keys.sys, "platform", "win32")
    monkeypatch.setattr(
        media_keys,
        "_build_windows_media_key_handler",
        lambda player: FakeHandler(player),
    )
    player = _FakePlayer()

    handler = media_keys.register_media_key_handler(player)

    assert handler is installed[0]
    assert handler.player is player


def test_register_media_key_handler_returns_none_when_windows_install_fails(monkeypatch):
    class FakeHandler:
        def install(self) -> bool:
            return False

    monkeypatch.setattr(media_keys.sys, "platform", "win32")
    monkeypatch.setattr(
        media_keys,
        "_build_windows_media_key_handler",
        lambda player: FakeHandler(),
    )

    assert media_keys.register_media_key_handler(_FakePlayer()) is None


def test_macos_handler_close_removes_event_monitor():
    removed: list[object] = []

    class FakeNSEvent:
        @staticmethod
        def removeMonitor_(monitor: object) -> None:
            removed.append(monitor)

    class FakeAppKit:
        NSEvent = FakeNSEvent

    monitor = object()
    handler = media_keys._MacMediaKeyHandler(FakeAppKit, monitor)

    handler.close()
    handler.close()

    assert removed == [monitor]
