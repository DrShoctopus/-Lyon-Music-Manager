# Build scripts

End-to-end Windows build for this branch (WMP / `main`).

## `build-windows.ps1`

One command, from a fresh clone, takes you to a distributable zip.

```powershell
# from the project root
scripts\build-windows.ps1
```

### What it does

1. Locates Python 3.14 (`py -3.14` first, then `python` if it's 3.14).
2. Creates `.venv\` and upgrades pip.
3. Installs `requirements.txt` + `pyinstaller`.
4. Downloads `ffmpeg.exe` (gyan.dev essentials build) and `discid.dll`
   (MetaBrainz libdiscid v0.6.4) into `bin\` if not already present.
5. Smoke-tests `from lyon.app import main`.
6. Runs `pyinstaller --noconfirm build\lyon.spec`.
7. Zips the result into `dist\LyonMusicManager-windows.zip`.

### Prerequisites

- **Python 3.14 (64-bit)** — https://www.python.org/downloads/. Tick
  *Add Python to PATH* during install.

### Flags

- `-SkipBinaries` — don't re-download `ffmpeg.exe` / `discid.dll` if
  they're already in `bin\`. Useful for repeat builds.
- `-SkipZip` — produce the PyInstaller bundle in `dist\` but don't
  zip it.
- `-Clean` — wipe `.venv`, `build\`, `dist\` before building.

### Output

`dist\LyonMusicManager-windows.zip` — distribute this file. The
recipient unzips it, runs `LyonMusicManager.exe` from the unzipped
folder. No installer / no setup wizard.

> **Note.** Copy the *whole folder* alongside the `.exe` — there are
> dozens of DLLs and the Python runtime in there. Just shipping the
> `.exe` won't work.

### If you'd rather have a real installer

The Spotify branch (`claude/spotify-youtube-WUsXc`) ships an Inno Setup
script and its `build-windows.ps1` produces a real
`LyonMusicManager-Setup.exe` instead of a zip.

### If PowerShell blocks the script

Run once in a PowerShell window (per-user scope):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then `scripts\build-windows.ps1` will run.
