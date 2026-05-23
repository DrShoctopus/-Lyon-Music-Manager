# Build scripts

End-to-end Windows build for this branch (WMP / `main`).

## `build-windows.ps1`

One command, from a fresh clone, takes you to a distributable zip.

```powershell
# from the project root
scripts\build-windows.ps1
```

### What it does

1. Locates Python 3.11 (`py -3.11` first, then `python` if it's 3.11).
2. Creates `.venv\` and upgrades pip.
3. Installs `requirements-build.txt`.
4. Downloads `ffmpeg.exe` (gyan.dev essentials build), the latest Windows x64
   Chromaprint `fpcalc.exe`, `discid.dll` (MetaBrainz libdiscid v0.6.4), and
   the VideoLAN VLC runtime into `bin\` if not already present. Existing
   `fpcalc.exe` is refreshed when it is not the latest Chromaprint release.
5. Smoke-tests `from lyon.app import main`, creation of a libVLC media player
   through python-vlc, and fpcalc availability.
6. Runs `pyinstaller --noconfirm build\lyon.spec`.
7. Zips the result into `dist\SeaLyonMediaManager-{version}-windows.zip`.
8. Builds `dist\SeaLyonMediaManager-{version}-Setup.exe` when Inno Setup 6 is
   installed.

### Prerequisites

- **Python 3.11 (64-bit)** — https://www.python.org/downloads/. Tick
  *Add Python to PATH* during install.

### Flags

- `-SkipBinaries` — don't re-download `ffmpeg.exe`, `fpcalc.exe`,
  `discid.dll`, or `bin\vlc\` if they're already present. Useful for repeat
  builds.
- `-SkipZip` — produce the PyInstaller bundle in `dist\` but don't
  zip it.
- `-SkipInstaller` — skip the Inno Setup installer step.
- `-Clean` — wipe `.venv`, `dist\`, and generated PyInstaller artefacts before building.

### Output

`dist\SeaLyonMediaManager-{version}-windows.zip` — distribute this file. The
recipient unzips it, runs `LyonMusicManager.exe` from the unzipped
folder. The zip itself has no setup wizard.

> **Note.** Copy the *whole folder* alongside the `.exe` — there are
> dozens of DLLs and the Python runtime in there. Just shipping the
> `.exe` won't work.

The script also produces `dist\SeaLyonMediaManager-{version}-Setup.exe` when
Inno Setup 6 is installed.

### If PowerShell blocks the script

Run once in a PowerShell window (per-user scope):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then `scripts\build-windows.ps1` will run.
