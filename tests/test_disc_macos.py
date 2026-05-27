from __future__ import annotations

import subprocess

from lyon.core import disc_macos
from lyon.core.disc_macos import MacOpticalDrive


def test_eject_drive_targets_selected_device(monkeypatch):
    calls: list[list[str]] = []
    drive = MacOpticalDrive(
        bsd_name="disk4",
        device_path="/dev/disk4",
        raw_path="/dev/rdisk4",
        vendor="",
        product="",
        is_ejectable=True,
    )
    monkeypatch.setattr(disc_macos.sys, "platform", "darwin")

    def fake_run(cmd, *, check, timeout):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(disc_macos.subprocess, "run", fake_run)

    assert disc_macos.eject_drive(drive) is True
    assert calls == [["/usr/sbin/diskutil", "eject", "/dev/disk4"]]
