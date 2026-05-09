# Lyon Music Manager

Lyon Music Manager is a Windows-focused desktop music app for ripping audio
CDs to FLAC, organizing a local music library, playing tracks, and browsing
YouTube from one Windows Media Player-inspired interface.

The app is built with Python, PySide6, Qt Multimedia, Qt WebEngine, SQLite,
Mutagen, MusicBrainz, Cover Art Archive, ffmpeg, and libdiscid.

## Current capabilities

- **Windows Media Player-style shell** with a dark gradient theme, orange accent
  controls, tabbed navigation, a status bar, and a persistent transport bar.
- **Library management** backed by SQLite in the user's app-data directory.
  The scanner imports common audio formats (`.flac`, `.mp3`, `.m4a`, `.aac`,
  `.ogg`, `.opus`, `.wav`, `.wma`) and reads tags with Mutagen.
- **Library browsing and search** by artist, album, and track, including
  fallbacks for blank metadata such as `Unknown Artist` and `Unknown Album`.
- **Playback queue** powered by `QMediaPlayer`, including play/pause, previous,
  next, seek/scrub, volume, mute, shuffle, repeat-all, repeat-one, enqueue, and
  a Now Playing view with cover art.
- **Audio CD detection** on Windows using the Win32 API and libdiscid.
- **MusicBrainz metadata lookup** by disc ID, plus manual artist/album search
  from the ripper view.
- **Cover Art Archive support** for downloading album art when enabled.
- **CD-to-FLAC ripping** through ffmpeg/libcdio, with per-track output, FLAC
  compression settings, Vorbis comments, embedded cover art, and optional disc
  eject after a successful rip.
- **Automatic rip organization** under the configured music root using
  `<Artist>/<Year> - <Album>/<Track> - <Title>.flac`.
- **In-app YouTube tab** using Qt WebEngine when `PySide6-Addons` is installed;
  the app shows a friendly installation message if WebEngine is unavailable.
- **Windows packaging** through PyInstaller, plus a PowerShell build script and
  a manual GitHub Actions workflow that can produce a distributable zip.

## Project status

This is currently a desktop application source tree rather than an installer
repository. It is optimized for Windows 10/11 because CD drive detection,
libdiscid loading, and audio-CD ripping are Windows-specific. Most modules are
importable and testable on other platforms, and the UI can be launched for
development where PySide6 is available, but physical CD ripping is expected to
work on Windows only.

The application version is defined in `lyon/__init__.py`.

## Requirements

### Runtime Python packages

Install the packages from `requirements.txt`:

- `PySide6` and `PySide6-Addons` for the desktop UI, multimedia playback, and
  the optional YouTube WebEngine tab.
- `mutagen` for reading and writing audio tags.
- `musicbrainzngs` and `requests` for metadata and artwork lookup.
- `Pillow` for image handling.
- `discid` on Windows for MusicBrainz disc IDs.

### External binaries for ripping

CD ripping and disc identification require external binaries. Put them in
`bin/` at the project root or otherwise make them available on `PATH`:

```text
bin/
  ffmpeg.exe
  discid.dll
```

Notes:

- Some older documentation and upstream packages refer to the libdiscid DLL as
  `libdiscid.dll`; the current build script and PyInstaller spec expect
  `discid.dll`.
- `ffmpeg.exe` must be a build with CDDA/libcdio support. The Windows
  essentials builds from gyan.dev are the intended source used by the build
  automation.
- The app can still launch without these files, but CD detection and ripping
  will not be functional.

## Quick start from source

On Windows PowerShell or `cmd.exe` from the project root:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Optional for ripping, required for a fully functional app:
:: place ffmpeg.exe and discid.dll in bin\

py main.py
```

On macOS or Linux, use your platform's Python virtual environment commands and
run `python main.py`. Non-Windows platforms are useful for UI/library
experimentation and tests, but CD-drive functionality is intentionally disabled
outside Windows.

## Using the app

1. **Configure settings**
   - Open **Settings**.
   - Choose the music root. The default is `Music\Lyon` under the current user.
   - Set FLAC compression from `0` (fastest) to `8` (smallest files).
   - Optionally set a default CD drive such as `D:`.
   - Update the MusicBrainz contact value before redistributing or doing heavy
     metadata lookups.

2. **Build or scan a library**
   - Open **Library**.
   - Use **Add Folder** to scan an existing music folder.
   - Use **Rescan** to re-read saved library roots or the configured music root.
   - Use **Remove Missing** to prune files that no longer exist.

3. **Play music**
   - Select an album or search for tracks in **Library**.
   - Double-click a track or use play/enqueue actions.
   - Control playback from the bottom transport bar or the **Now Playing** tab.

4. **Rip a CD**
   - Put `ffmpeg.exe` and `discid.dll` in `bin/` first.
   - Insert an audio CD and open **Rip**.
   - Click **Refresh Drives** if needed, then **Read Disc**.
   - Review or edit artist, album, year, and track titles.
   - Click **Search Online** if automatic metadata needs correction.
   - Click **Rip CD**. Output is written as FLAC under the configured music
     root and is added to the library after completion.

5. **Browse YouTube**
   - Open **YouTube**.
   - Search from the address field or paste a URL.
   - When leaving the tab, the app pauses page video elements and hides the
     music transport bar while the web view is active.

## Data locations

User data is stored outside the repository:

- **Windows:** `%APPDATA%\LyonMusicManager\`
- **Other platforms:** `$XDG_CONFIG_HOME/LyonMusicManager/` or
  `~/.config/LyonMusicManager/`

Important files in that directory include:

- `settings.json` for app preferences.
- `library.db` for the SQLite music-library index.

Ripped music defaults to `Music\Lyon` under the current user and can be changed
in Settings.

## Building for Windows

### Recommended local build script

The repository includes an end-to-end PowerShell script:

```powershell
scripts\build-windows.ps1
```

The script creates `.venv`, installs dependencies and PyInstaller, downloads
`ffmpeg.exe` and `discid.dll` when missing, smoke-tests imports, builds the
PyInstaller bundle, and writes:

```text
dist\LyonMusicManager-windows.zip
```

Useful flags:

```powershell
scripts\build-windows.ps1 -Clean
scripts\build-windows.ps1 -SkipBinaries
scripts\build-windows.ps1 -SkipZip
```

See `scripts/README.md` for script-specific details.

### Manual PyInstaller build

For a manual build on Windows:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
pyinstaller build\lyon.spec
```

The bundle is created at:

```text
dist\LyonMusicManager\
```

Distribute the whole folder or zip its contents. Shipping only the executable
will not work because the app depends on bundled Python, Qt, and DLL files.

See `docs/BUILD.md` for the longer build guide.

### GitHub Actions build

The workflow at `.github/workflows/windows-build.yml` is a manual
`workflow_dispatch` Windows build. It installs dependencies, downloads ffmpeg
and libdiscid, runs PyInstaller, and uploads `LyonMusicManager-windows.zip` as
an artifact.

## Repository layout

```text
main.py                         Top-level launcher
lyon/__init__.py                App name and version
lyon/app.py                     QApplication setup and main window launch
lyon/core/cd_detect.py          Windows optical-drive and libdiscid helpers
lyon/core/library.py            SQLite library index and search queries
lyon/core/metadata.py           MusicBrainz and Cover Art Archive lookups
lyon/core/player.py             QMediaPlayer queue, shuffle, repeat, volume
lyon/core/ripper.py             ffmpeg-backed CD-to-FLAC worker
lyon/core/settings.py           Settings defaults, persistence, bin lookup
lyon/core/tagger.py             FLAC/Vorbis comment and cover-art writer
lyon/ui/                        Main window, tabs, dialogs, styles, widgets
build/lyon.spec                 PyInstaller build definition
docs/BUILD.md                   Windows build guide
scripts/build-windows.ps1       End-to-end Windows build script
scripts/README.md               Build-script documentation
tests/                          Unit tests for metadata and library behavior
requirements.txt                Python runtime dependencies
```

## Testing

The test suite uses `pytest`. Install it in your development environment if it
is not already present:

```cmd
pip install pytest
pytest
```

Current tests cover MusicBrainz multi-disc metadata selection and library query
fallbacks for blank artist/album metadata.

## Troubleshooting

- **`ffmpeg not found` while ripping**: place `bin\ffmpeg.exe` in the project
  root or install ffmpeg on `PATH`.
- **No CD drive appears**: CD detection is Windows-only and relies on the Win32
  optical-drive APIs. Confirm the drive is visible to Windows and contains an
  audio CD.
- **Disc metadata does not resolve**: confirm internet access and set a real
  MusicBrainz contact string in Settings. MusicBrainz may rate-limit generic or
  abusive clients.
- **YouTube tab says WebEngine is unavailable**: install `PySide6-Addons` into
  the active environment and restart the app.
- **Built zip does not run on another machine**: distribute the complete
  `dist\LyonMusicManager\` folder or the generated zip, not just
  `LyonMusicManager.exe`.

## Credits and third-party services

Lyon Music Manager uses MusicBrainz metadata, Cover Art Archive artwork,
ffmpeg/libcdio for CD audio extraction, libdiscid for disc IDs, Mutagen for tag
handling, and Qt/PySide6 for the desktop UI. Respect the MusicBrainz access
policy by setting an appropriate contact value before distributing builds.
