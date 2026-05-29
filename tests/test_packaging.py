from __future__ import annotations

import runpy
import re
import sys
import types
from pathlib import Path

import pytest


def test_pyinstaller_spec_resolves_repo_root(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    captured = {}

    pil = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")

    class FakeImage:
        def convert(self, *_args, **_kwargs):
            return self

        def save(self, *_args, **_kwargs):
            pass

    image_mod.open = lambda *_args, **_kwargs: FakeImage()
    pil.Image = image_mod
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_mod)

    def analysis(*args, **kwargs):
        captured["scripts"] = args[0]
        captured["pathex"] = kwargs["pathex"]
        captured["datas"] = kwargs["datas"]
        captured["binaries"] = kwargs["binaries"]
        return types.SimpleNamespace(
            pure=[],
            zipped_data=[],
            scripts=[],
            binaries=[],
            zipfiles=[],
            datas=[],
        )

    globals_for_spec = {
        "SPECPATH": str(repo / "build" / "lyon.spec"),
        "Analysis": analysis,
        "PYZ": lambda *_args, **_kwargs: object(),
        "EXE": lambda *_args, **_kwargs: object(),
        "COLLECT": lambda *_args, **_kwargs: object(),
        "BUNDLE": lambda *_args, **_kwargs: object(),
    }

    runpy.run_path(str(repo / "build" / "lyon.spec"), init_globals=globals_for_spec)

    assert captured["scripts"] == [str(repo / "main.py")]
    assert captured["pathex"] == [str(repo)]
    assert any(str(repo / "docs" / "brand") in src for src, _dest in captured["datas"])
    assert (
        str(repo / "lyon" / "ui" / "assets"),
        str(Path("lyon") / "ui" / "assets"),
    ) in captured["datas"]


@pytest.mark.parametrize("lockfile", ["requirements.txt", "requirements-build.txt"])
def test_lockfiles_include_macos_runtime_dependencies(lockfile):
    repo = Path(__file__).resolve().parents[1]
    text = (repo / lockfile).read_text(encoding="utf-8").casefold()

    assert re.search(r"discid==1\.3\.0 ; .*sys_platform == 'darwin'", text)
    assert "pyobjc-framework-cocoa==12.1 ; sys_platform == 'darwin'" in text
    assert "pyobjc-framework-diskarbitration==12.1 ; sys_platform == 'darwin'" in text


def test_macos_build_gate_counts_pytest_collected_output():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "tests? collected" in workflow
    assert "tests? selected" not in workflow


def test_macos_workflow_skips_signing_when_credentials_are_missing():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "Detect macOS signing credentials" in workflow
    assert "id: macos-signing" in workflow
    assert "MACOS_SIGNING_ENABLED=0" in workflow
    assert "unsigned DMG will be produced" in workflow
    assert "if: steps.macos-signing.outputs.enabled == '1'" in workflow
    assert "MACOS_SIGNING_ENABLED: ${{ steps.macos-signing.outputs.enabled }}" in workflow


def test_macos_dmg_script_can_leave_dmg_unsigned():
    repo = Path(__file__).resolve().parents[1]
    script = (repo / "scripts" / "build-macos-dmg.sh").read_text(encoding="utf-8")

    assert "MACOS_SIGNING_ENABLED" in script
    assert "leaving unsigned DMG" in script
    assert "APPLE_TEAM_ID is required when MACOS_SIGNING_ENABLED=1" in script


def test_macos_workflow_uses_pinned_arm64_ffmpeg_source():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "FFMPEG_VERSION: \"6.1.1\"" in workflow
    assert "FFMPEG_URL: \"https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-darwin-arm64.gz\"" in workflow
    assert "FFMPEG_SHA256: \"8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa\"" in workflow
    assert "evermeet.cx" not in workflow
    assert "mac-vendor-ffmpeg${{ env.FFMPEG_VERSION }}" in workflow


def test_macos_workflow_pins_vendor_archive_checksums():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "FPCALC_SHA256: \"9c5d9565d2396dbcf0e1d797e1ffdf1e19242f3bed88ac3200e144286b57ede6\"" in workflow
    assert "LIBDISCID_URL: \"https://github.com/metabrainz/libdiscid/releases/download/v0.6.4/libdiscid-0.6.4.tar.gz\"" in workflow
    assert "LIBDISCID_SHA256: \"dd5e8f1c9aead442e23b749a9cc9336372e62e88ad7079a2b62895b0390cb282\"" in workflow
    assert "musicbrainz.org/static/libdiscid" not in workflow
    assert "fpcalc${{ env.FPCALC_VERSION }}" in workflow


def test_macos_vendor_script_verifies_and_replaces_vendor_archives():
    repo = Path(__file__).resolve().parents[1]
    script = (repo / "scripts" / "fetch-macos-vendor-binaries.sh").read_text(encoding="utf-8")

    assert "FFMPEG_SHA256" in script
    assert "FPCALC_SHA256" in script
    assert "LIBDISCID_SHA256" in script
    assert "ffmpeg-darwin-arm64.gz" in script
    assert "github.com/metabrainz/libdiscid" in script
    assert "Cached ffmpeg is not arm64; refetching" in script
    assert "gzip -dc" in script
    assert "checksum mismatch" in script
    assert "evermeet.cx" not in script
    assert "musicbrainz.org/static/libdiscid" not in script


def test_macos_bundle_script_cleans_up_vlc_mount():
    repo = Path(__file__).resolve().parents[1]
    script = (repo / "scripts" / "build-macos-bundle.sh").read_text(encoding="utf-8")

    assert "cleanup_vlc_mount" in script
    assert "trap cleanup_vlc_mount EXIT" in script
    assert "mkdir -p \"$VLC_MOUNT\"" in script
