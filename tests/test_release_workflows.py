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

    assert 'DENO_VERSION: "2.8.1"' in workflow
    assert (
        'DENO_URL: "https://github.com/denoland/deno/releases/download/v2.8.1/'
        'deno-x86_64-pc-windows-msvc.zip"'
    ) in workflow
    assert (
        'DENO_SHA256: "5fb5bac71f609fb91ec8960fb290885aadc27eeb22f07a8eca0c3db6be38b11a"'
        in workflow
    )
    assert "deno-${{ env.DENO_VERSION }}" in workflow
    assert "Fetch Deno runtime (hash-verified)" in workflow
    assert "bin\\deno.exe --version" in workflow
    assert "'bin\\deno.exe'" in workflow
    assert "Packaged app is missing deno.exe" in workflow


def test_macos_workflow_bundles_pinned_deno_runtime_for_youtube_solver():
    workflow = (REPO_ROOT / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert 'DENO_VERSION: "2.8.1"' in workflow
    assert (
        'DENO_URL: "https://github.com/denoland/deno/releases/download/v2.8.1/'
        'deno-aarch64-apple-darwin.zip"'
    ) in workflow
    assert (
        'DENO_SHA256: "8154e2de0ee8c1cae31fa88e078724aaef0295fab9fd2ad6f8520389cee908f6"'
        in workflow
    )
    assert "deno${{ env.DENO_VERSION }}" in workflow
    assert "STAGED_DENO: vendor-mac/deno" in workflow
    assert "Inject libVLC, plugins, ffmpeg, fpcalc, deno, libdiscid" in workflow
