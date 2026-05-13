# PyInstaller spec for Lyon Music Manager.
# Build on Windows with:  pyinstaller build/lyon.spec
#
# Drop these into a `bin/` folder at the project root before building:
#   bin/ffmpeg.exe         (static Windows build, e.g. from gyan.dev)
#   bin/discid.dll         (libdiscid Windows release)
#   optional: a VLC runtime directory if you choose to bundle libVLC
#
# They are bundled next to the .exe so the app works offline.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "bin"

binaries = []
datas = []

if BIN.exists():
    for entry in BIN.iterdir():
        if entry.is_file():
            binaries.append((str(entry), "bin"))
        elif entry.is_dir():
            for child in entry.rglob("*"):
                if child.is_file():
                    dest = Path("bin") / entry.name / child.relative_to(entry).parent
                    datas.append((str(child), str(dest)))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["discid", "musicbrainzngs", "mutagen", "PIL", "vlc"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LyonMusicManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LyonMusicManager",
)
