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

from PIL import Image

SPEC_DIR = Path(SPECPATH).resolve()
if not SPEC_DIR.is_dir():
    SPEC_DIR = SPEC_DIR.parent
ROOT = SPEC_DIR.parent
BIN = ROOT / "bin"
BRAND_DIRS = (
    ROOT / "docs" / "brand",
    ROOT / "Docs" / "brand",
)
ICON_PNG_NAME = "lyon-app-icon.png"
GENERATED_ICON = ROOT / "build" / "lyon-app-icon.ico"

binaries = []
datas = []
icon_file = None


def windows_icon_from_png(icon_png: Path) -> str:
    """Create a temporary Windows .ico for PyInstaller from the brand PNG."""
    GENERATED_ICON.parent.mkdir(parents=True, exist_ok=True)
    Image.open(icon_png).convert("RGBA").save(
        GENERATED_ICON,
        format="ICO",
        sizes=[
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )
    return str(GENERATED_ICON)

if BIN.exists():
    for entry in BIN.iterdir():
        if entry.is_file():
            binaries.append((str(entry), "bin"))
        elif entry.is_dir():
            for child in entry.rglob("*"):
                if child.is_file():
                    dest = Path("bin") / entry.name / child.relative_to(entry).parent
                    datas.append((str(child), str(dest)))

for brand_dir in BRAND_DIRS:
    if brand_dir.exists():
        for asset in brand_dir.iterdir():
            if asset.is_file():
                datas.append((str(asset), str(Path("docs") / "brand")))
        icon_candidate = brand_dir / ICON_PNG_NAME
        if icon_candidate.exists():
            icon_file = windows_icon_from_png(icon_candidate)
        break

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "discid",
        "musicbrainzngs",
        "mutagen",
        "PIL",
        "vlc",
        "defusedxml",
        "requests",
        "urllib3",
        "certifi",
        "yt_dlp",
    ],
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
    icon=icon_file,
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
