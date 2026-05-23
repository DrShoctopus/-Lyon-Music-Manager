from __future__ import annotations

from lyon.core import diagnostics
from lyon.core.diagnostics import (
    DependencyCheck,
    DiagnosticStatus,
    check_vlc,
    summarize_dependency_checks,
)


def test_summarize_dependency_checks_all_ready() -> None:
    checks = [DependencyCheck("example", DiagnosticStatus.OK, "ready", "none")]

    assert summarize_dependency_checks(checks) == "All optional runtime dependencies look ready."


def test_summarize_dependency_checks_counts_missing_and_warnings() -> None:
    checks = [
        DependencyCheck("missing", DiagnosticStatus.MISSING, "missing", "fix"),
        DependencyCheck("warning", DiagnosticStatus.WARNING, "warning", "fix"),
        DependencyCheck("ready", DiagnosticStatus.OK, "ready", "none"),
    ]

    assert summarize_dependency_checks(checks) == "Dependency checks need attention: 1 missing, 1 warning."


def test_vlc_check_warns_when_only_vlc_app_is_on_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(diagnostics, "bundled_bin_dir", lambda: tmp_path)
    monkeypatch.setattr(diagnostics, "_has_module", lambda module: module == "vlc")
    monkeypatch.setattr(diagnostics, "_system_libvlc_present", lambda: False)
    monkeypatch.setattr(diagnostics, "_path_tool", lambda *names: "/usr/bin/vlc")

    check = check_vlc()

    assert check.status is DiagnosticStatus.WARNING
    assert "libVLC was not found" in check.detail


def test_dlna_network_check_warns_when_udp_socket_is_denied(monkeypatch) -> None:
    class DeniedSocket:
        def setsockopt(self, *_args):
            pass

        def bind(self, *_args):
            raise PermissionError("Operation not permitted")

        def close(self):
            pass

    monkeypatch.setattr(diagnostics.socket, "socket", lambda *_args: DeniedSocket())

    check = diagnostics.check_dlna_network()

    assert check.status is DiagnosticStatus.WARNING
    assert "Operation not permitted" in check.detail
    assert "Local Network" in check.fix


def test_dlna_network_check_warns_when_advertised_address_is_loopback(monkeypatch) -> None:
    class WorkingSocket:
        def setsockopt(self, *_args):
            pass

        def bind(self, *_args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(diagnostics.socket, "socket", lambda *_args: WorkingSocket())
    monkeypatch.setattr(diagnostics, "_local_ip", lambda: "127.0.0.1")

    check = diagnostics.check_dlna_network()

    assert check.status is DiagnosticStatus.WARNING
    assert "127.0.0.1" in check.detail
    assert "LAN" in check.fix
