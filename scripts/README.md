# Build scripts

End-to-end Windows build for this branch.

## `build-windows.ps1`

One command, from a fresh clone, takes you to a signed-up `Setup.exe`.

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
7. Runs Inno Setup against `installer\lyon.iss`, producing
   `installer\Output\LyonMusicManager-Setup.exe`.

### Prerequisites

- **Python 3.14 (64-bit)** — https://www.python.org/downloads/. Tick
  *Add Python to PATH*.
- **Inno Setup 6** — https://jrsoftware.org/isinfo.php. Default install
  location works.

### Flags

- `-SkipBinaries` — don't re-download `ffmpeg.exe` / `discid.dll` if
  they're already in `bin\`. Useful for repeat builds.
- `-SkipInstaller` — produce the PyInstaller bundle in `dist\` but
  don't run Inno Setup. Useful if Inno Setup isn't installed.
- `-Clean` — wipe `.venv`, `build\`, `dist\`, and `installer\Output\`
  before building.

### Output

`installer\Output\LyonMusicManager-Setup.exe` — distribute this file.
Users double-click it to install Lyon Music Manager with Start menu
shortcut, optional desktop shortcut, optional `.flac` association, and
a proper uninstaller.

### If PowerShell blocks the script

Run once in a PowerShell window (per-user scope, won't survive logout
unless you confirm):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then `scripts\build-windows.ps1` will run.
