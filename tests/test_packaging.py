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
    assert "pyobjc-framework-cocoa==10.3.2 ; sys_platform == 'darwin'" in text
    assert "pyobjc-framework-diskarbitration==10.3.2 ; sys_platform == 'darwin'" in text


def test_macos_build_gate_counts_pytest_collected_output():
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "macos-build.yml").read_text(encoding="utf-8")

    assert "tests? collected" in workflow
    assert "tests? selected" not in workflow
