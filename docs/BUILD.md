# Building Lyon Music Manager for Windows

Tested on Windows 10/11 with Python 3.11. Should also run on Windows 8.1 if
you grab a Python build that still supports it (3.8 was the last).

## 1. Prerequisites

- **Python 3.11+ (64-bit)** from python.org — tick "Add Python to PATH".
- **ffmpeg.exe** (Windows static build, e.g. https://www.gyan.dev/ffmpeg/builds/).
  The full / "essentials" build is fine; we need libcdio support, which is in
  the standard Windows builds.
- **libdiscid.dll** (Windows 64-bit) from
  https://musicbrainz.org/doc/libdiscid#Download

Place both files into `bin/` at the project root:

```
bin\
  ffmpeg.exe
  libdiscid.dll
```

## 2. Install dependencies

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

## 3. Run from source

```cmd
py main.py
```

## 4. Build a stand-alone bundle

```cmd
pyinstaller build\lyon.spec
```

The packaged app appears under `dist\LyonMusicManager\`. Double-click
`LyonMusicManager.exe` or zip the folder for distribution.

## 5. Optional: single-file build

Edit `build/lyon.spec`, change the `EXE(...)` block to use
`a.binaries, a.zipfiles, a.datas` directly (i.e. drop the `COLLECT` step) and
set `console=False, onefile=True`. PyInstaller will produce a one-file `.exe`,
which trades faster startup for a slower first launch.

## Troubleshooting

- **"ffmpeg not found"** — check that `bin\ffmpeg.exe` exists, or install
  ffmpeg system-wide and add to PATH.
- **CD not detected** — confirm `bin\libdiscid.dll` exists. The app uses
  Windows API `GetDriveType` to find optical drives, so virtual drives may
  not show up.
- **Metadata never resolves** — check internet access, CTDB availability, and the MusicBrainz
  contact value in *Settings*. Hammering MusicBrainz with a generic
  user-agent gets your IP rate-limited.
