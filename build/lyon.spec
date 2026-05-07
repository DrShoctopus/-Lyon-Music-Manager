# PyInstaller spec for Lyon Music Manager.
# Build on Windows with:  pyinstaller build/lyon.spec
#
# Place these files into a `bin/` folder at the project root before building:
#   bin/ffmpeg.exe         (static Windows build, e.g. from gyan.dev)
#   bin/libdiscid.dll      (Win64 build from MetaBrainz)
#
# They are bundled next to the .exe so the app works offline.
# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "bin"

binaries = []
datas = []

if BIN.exists():
    for entry in BIN.iterdir():
        if entry.is_file():
            binaries.append((str(entry), "bin"))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["discid", "musicbrainzngs", "mutagen", "PIL"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
