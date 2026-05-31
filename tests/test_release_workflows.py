from __future__ import annotations

import json
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
    assert "--macos-minimum-system-version" in workflow
    assert "MACOS_MINIMUM_SYSTEM_VERSION" in workflow
    assert "SeaLyonMediaManager-${ver}-Setup.exe" in workflow
    assert "dist/appcast.xml" in workflow


def test_macos_tag_release_reads_windows_asset_from_draft_aware_release_listing():
    workflow = (REPO_ROOT / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert 'gh api "repos/${repo}/releases?per_page=100"' in workflow
    assert "release.get(\"tag_name\") != tag" in workflow
    assert "releases/tags/${tag}" not in workflow


def test_macos_artifact_name_does_not_use_branch_ref_name():
    workflow = (REPO_ROOT / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "SeaLyonMediaManager-${{ github.ref_name }}-macos" not in workflow
    assert "SeaLyonMediaManager-${{ steps.appver.outputs.version }}-macos" in workflow
    assert "version=$ver" in workflow


def test_windows_workflow_bundles_pinned_deno_runtime_for_youtube_solver():
    workflow = (REPO_ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "build" / "vendor-runtimes.json").read_text(encoding="utf-8"))

    assert manifest["deno"]["windows"]["url"].endswith("deno-x86_64-pc-windows-msvc.zip")
    assert "Load Deno vendor metadata" in workflow
    assert "ConvertFrom-Json" in workflow
    assert "deno-${{ steps.deno.outputs.version }}" in workflow
    assert "Invoke-WebRequestWithRetry -Uri $env:DENO_URL -OutFile deno.zip" in workflow
    assert "Fetch Deno runtime (hash-verified)" in workflow
    assert "bin\\deno.exe --version" in workflow
    assert "'bin\\deno.exe'" in workflow
    assert "Packaged app is missing deno.exe" in workflow


def test_macos_workflow_bundles_pinned_deno_runtime_for_youtube_solver():
    workflow = (REPO_ROOT / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")
    manifest = json.loads((REPO_ROOT / "build" / "vendor-runtimes.json").read_text(encoding="utf-8"))

    assert manifest["deno"]["macos_arm64"]["url"].endswith("deno-aarch64-apple-darwin.zip")
    assert "Load Deno vendor metadata" in workflow
    assert "build/vendor-runtimes.json" in workflow
    assert "deno${{ steps.deno.outputs.version }}" in workflow
    assert "STAGED_DENO: vendor-mac/deno" in workflow
    assert "Inject libVLC, plugins, ffmpeg, fpcalc, deno, libdiscid" in workflow
