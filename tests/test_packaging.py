from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path


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
