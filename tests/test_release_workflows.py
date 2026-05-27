from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tag_release_fetches_current_appcast_before_generating_new_one():
    workflow = (REPO_ROOT / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")

    fetch_pos = workflow.find("Fetch current appcast history")
    generate_pos = workflow.find("Generate appcast.xml")

    assert fetch_pos != -1
    assert generate_pos != -1
    assert fetch_pos < generate_pos
    assert "Invoke-WebRequest" in workflow
    assert "https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml" in workflow


def test_macos_tag_release_regenerates_multi_os_appcast():
    workflow = (REPO_ROOT / ".github/workflows/macos-build.yml").read_text(encoding="utf-8")

    attach_pos = workflow.find("Attach to GitHub Release")
    appcast_pos = workflow.find("Generate multi-OS appcast.xml")

    assert attach_pos != -1
    assert appcast_pos != -1
    assert attach_pos < appcast_pos
    assert "--macos-installer-url" in workflow
    assert "--macos-installer-size" in workflow
    assert "SeaLyonMediaManager-${ver}-Setup.exe" in workflow
    assert "dist/appcast.xml" in workflow
