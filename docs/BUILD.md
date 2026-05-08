# Building Lyon Music Manager for Windows

The default packaging output is **`LyonMusicManager-Setup.exe`** — a real
Windows installer built with PyInstaller (to bundle the app) and Inno Setup
(to wrap the bundle in a Setup wizard with Start menu / desktop shortcuts
and an uninstaller).

Tested on Windows 10/11 with Python 3.11. Python 3.13 and 3.14 also work.
Windows 8.1 is no longer supported because Python 3.14 dropped it; if you
need 8.1, build with Python 3.11.

## 1. Prerequisites

Install once on the build machine:

- **Python 3.11+ (64-bit)** — https://www.python.org/downloads/. Tick "Add
  Python to PATH" during install.
- **Inno Setup 6** — https://jrsoftware.org/isinfo.php. Install with
  defaults; the compiler `iscc.exe` lands in
  `%ProgramFiles(x86)%\Inno Setup 6\`.
- **ffmpeg.exe** (Windows static build) — https://www.gyan.dev/ffmpeg/builds/
  ("essentials" is enough; we need libcdio for CDDA, included in standard
  Windows builds).
- **libdiscid.dll** (Windows 64-bit) —
  https://github.com/metabrainz/libdiscid/releases (rename to `discid.dll`
  if the archive uses that name; PySide's `discid` package looks for
  `discid.dll`).

Drop the two binaries into `bin\` at the project root:

```
bin\
  ffmpeg.exe
  discid.dll
```

## 2. Install Python dependencies

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

## 3. Run from source (optional)

```powershell
py main.py
```

## 4. Build the installer (default packaging step)

Two commands:

```powershell
# 4a. Bundle the app
py -m PyInstaller --noconfirm build\lyon.spec

# 4b. Wrap the bundle in a Setup wizard
& "${env:ProgramFiles(x86)}\Inno Setup 6\iscc.exe" installer\lyon.iss
```

Output: `installer\Output\LyonMusicManager-Setup.exe`. That single file is
what you ship.

What it does on the user's machine:

- Installs into `%LocalAppData%\Programs\Lyon Music Manager\` (per-user, no
  admin elevation needed) or `Program Files\Lyon Music Manager\` if the
  user picks "Install for all users" in the elevation dialog.
- Adds a Start menu entry.
- Optionally creates a desktop shortcut (checkbox during install).
- Optionally associates `.flac` files with the app (unchecked by default).
- Registers a proper uninstaller in *Settings → Apps*.

## 5. Building from source without an installer (just the folder)

If you'd rather distribute a zipped folder than an installer:

```powershell
py -m PyInstaller --noconfirm build\lyon.spec
# Zip dist\LyonMusicManager\ and ship the whole folder.
```

The `.exe` alone won't run — it relies on the dozens of DLLs and Python
runtime files in the same folder.

## 6. CI builds (recommended for cross-platform contributors)

The workflow [`.github/workflows/windows-build.yml`](../.github/workflows/windows-build.yml)
runs on every push and PR. It:

1. Sets up Python 3.11 on a `windows-latest` runner.
2. Installs requirements + PyInstaller.
3. Downloads `ffmpeg.exe` (gyan.dev essentials build) and `libdiscid.dll`
   (MetaBrainz v0.6.4) into `bin\`.
4. Runs PyInstaller with `build\lyon.spec`.
5. Installs Inno Setup via Chocolatey.
6. Compiles `installer\lyon.iss`.
7. Uploads `LyonMusicManager-Setup.exe` as the
   `LyonMusicManager-Setup` artifact (30-day retention).

To grab the installer: open the repo on GitHub → **Actions** tab → click
the latest run → scroll to **Artifacts** → download
`LyonMusicManager-Setup`. Unzip the artifact, run the `.exe`, follow the
wizard.

## Troubleshooting

- **"ffmpeg not found"** at runtime — the bundled `bin\ffmpeg.exe` was
  missing when PyInstaller ran. Make sure it's there before step 4a.
- **CD not detected** — `bin\discid.dll` missing or your drive isn't
  exposed to Windows as a CD-ROM. The app uses `GetDriveType` to find
  optical drives; virtual drives may not register.
- **"iscc.exe not found"** — install Inno Setup 6 (see Prerequisites) or
  use the CI workflow to build remotely.
- **Metadata never resolves** — check internet access and the MusicBrainz
  contact value in *Settings*. Hammering MusicBrainz with a generic
  user-agent gets your IP rate-limited.
