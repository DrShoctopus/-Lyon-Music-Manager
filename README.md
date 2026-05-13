<p align="center">
  <img src="docs/brand/lyon-readme-banner.svg" alt="Lyon Music Manager vintage robot brand banner" width="100%">
</p>

# Lyon Music Manager

Lyon Music Manager is a Windows-focused desktop music app for ripping audio CDs
to FLAC, organizing a local music library, playing tracks, and browsing YouTube
from one Windows Media Player-inspired interface.

The app is built with Python, PySide6, Qt Multimedia, Qt WebEngine, SQLite,
Mutagen, MusicBrainz, Cover Art Archive, ffmpeg, libdiscid, and libVLC.

## Current Status

`LMM-DEV` is an active desktop application branch. It includes the core music
library, playback, CD-ripping, YouTube, Windows build, and vintage robot branding
work. The app can be run from source for development, and Windows packaging is
available through PyInstaller and a manual GitHub Actions workflow.

This is still source-first rather than a polished public installer repository.
The app is optimized for Windows 10/11 because CD-drive detection, libdiscid, and
audio-CD ripping are Windows-specific. Most UI and library behavior can still be
developed on other platforms where PySide6 is available.

The application version is defined in `lyon/__init__.py`.

## Current Capabilities

- **Vintage robot startup branding** with a PySide6-drawn app icon and short
  splash screen at launch.
- **Windows Media Player-style shell** with a dark glossy theme, tabbed
  navigation, status messages, Settings access, and a persistent transport bar.
- **Library management** backed by SQLite in the user's app-data directory. The
  scanner imports `.flac`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wav`, and
  `.wma` files and reads tags with Mutagen.
- **Library browsing and search** by artist, album, and track, including
  fallbacks for blank metadata such as `Unknown Artist` and `Unknown Album`.
- **Playback queue** with a libVLC-backed local-audio engine and Qt Multimedia
  fallback, including play/pause, previous, next, seek/scrub, volume, mute,
  shuffle, repeat-all, repeat-one, enqueue, and a Now Playing view with cover
  art.
- **Library playback polish** including enqueue feedback, current-track
  highlighting, selected-track scrolling, and track tooltips with artist, album,
  time, and file type.
- **Six-band equalizer** with persisted settings. When libVLC is available the
  EQ is applied to playback; the Qt Multimedia fallback keeps the controls
  available but plays audio flat.
- **Audio CD detection** on Windows using Win32 optical-drive APIs and libdiscid.
- **CTDB metadata lookup with MusicBrainz fallback** by disc TOC, plus manual
  artist/album search from the ripper view.
- **Cover Art Archive support** for downloading album art when enabled.
- **CD-to-FLAC ripping** through ffmpeg/libcdio, with per-track output, FLAC
  compression settings, Vorbis comments, embedded cover art, overwrite
  confirmation, cancellation, and optional disc eject after a successful rip.
- **Automatic rip organization** under the configured music root using
  `<Artist>/<Year> - <Album>/<Track> - <Title>.flac`.
- **In-app YouTube tab** using Qt WebEngine when `PySide6-Addons` is installed,
  with search/URL navigation and automatic video pause when leaving the tab.
- **Windows packaging** through PyInstaller, plus a PowerShell build script and a
  manual GitHub Actions workflow that can produce a distributable zip.

## Requirements

### Runtime Python Packages

Install the packages from `requirements.txt`:

- `PySide6` for the desktop UI and multimedia playback.
- `PySide6-Addons` for the optional Qt WebEngine YouTube tab.
- `mutagen` for reading and writing audio tags.
- `musicbrainzngs` and `requests` for metadata and artwork lookup.
- `Pillow` for image handling.
- `python-vlc` for the preferred local playback backend and audible equalizer.
- `discid` on Windows for MusicBrainz disc IDs.

### External Binaries For Playback And Ripping

CD ripping, disc identification, and the preferred VLC playback backend require
external binaries. Put them in `bin/` at the project root for source runs and
Windows packaging:

```text
bin/
  ffmpeg.exe
  discid.dll
  vlc/
    libvlc.dll
    libvlccore.dll
    plugins/
```

Notes:

- Some libdiscid downloads name the DLL `libdiscid.dll`; the current build
  script and PyInstaller spec expect `discid.dll`.
- `ffmpeg.exe` must be a build with CDDA/libcdio support. The Windows essentials
  builds from gyan.dev are the intended source used by the build automation.
- `bin/vlc/` should contain the extracted 64-bit VLC runtime folder contents.
  It is optional for launching, but without it the app may use a system VLC
  install or fall back to Qt Multimedia. The fallback plays audio flat, so the
  six-band EQ will not audibly affect playback.
- The app can still launch without these files, but CD detection and ripping
  will not be functional without ffmpeg/libdiscid.

## Quick Start From Source

On Windows PowerShell or `cmd.exe` from the project root:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Optional for playback EQ and ripping, required for a fully functional app:
:: place ffmpeg.exe, discid.dll, and the extracted VLC runtime in bin\

py main.py
```

On macOS or Linux, use your platform's Python virtual environment commands and
run `python main.py`. Non-Windows platforms are useful for UI/library
experimentation and tests, but CD-drive functionality is intentionally disabled
outside Windows.

## Using The App

1. **Start the app**
   - Launch from source with `py main.py`.
   - The vintage robot splash appears briefly before the main window opens.

2. **Configure settings**
   - Open **Settings**.
   - Choose the music root. The default is `Music\Lyon` under the current user.
   - Set FLAC compression from `0` (fastest) to `8` (smallest files).
   - Optionally set a default CD drive such as `D:`.
   - Update the MusicBrainz contact value before redistributing or doing heavy
     metadata lookups.

3. **Build or scan a library**
   - Open **Library**.
   - Use **Add Folder** to scan an existing music folder.
   - Use **Rescan** to re-read saved library roots or the configured music root.
   - Use **Remove Missing** from the File menu to prune files that no longer
     exist.

4. **Play music**
   - Select an album or search for tracks in **Library**.
   - Double-click a track or use play/enqueue actions.
   - Control playback from the bottom transport bar or the **Now Playing** tab.
   - Use shuffle and repeat controls from the transport bar.
   - Open **6 Band EQ** to enable and adjust the persisted equalizer curve.

5. **Rip a CD**
   - Put `ffmpeg.exe` and `discid.dll` in `bin/` first.
   - Insert an audio CD and open **Rip**.
   - Click **Refresh Drives** if needed, then **Read Disc**.
   - Review or edit artist, album, year, and track titles.
   - Click **Search Online** if automatic metadata needs correction.
   - Click **Rip CD**. Output is written as FLAC under the configured music root
     and is added to the library after each track completes.

6. **Browse YouTube**
   - Open **YouTube**.
   - Search from the address field or paste a URL.
   - When leaving the tab, the app pauses page video elements and hides the music
     transport bar while the web view is active.

## Data Locations

User data is stored outside the repository:

- **Windows:** `%APPDATA%\LyonMusicManager\`
- **Other platforms:** `$XDG_CONFIG_HOME/LyonMusicManager/` or
  `~/.config/LyonMusicManager/`

Important files in that directory include:

- `settings.json` for app preferences.
- `library.db` for the SQLite music-library index.

Ripped music defaults to `Music\Lyon` under the current user and can be changed
in Settings.

## Building For Windows

### Recommended Local Build Script

The repository includes an end-to-end PowerShell script:

```powershell
scripts\build-windows.ps1
```

The script creates `.venv`, installs dependencies and PyInstaller, downloads
`ffmpeg.exe`, `discid.dll`, and the VLC runtime when missing, smoke-tests
imports plus VLC backend creation, builds the PyInstaller bundle, and writes:

```text
dist\LyonMusicManager-windows.zip
```

Useful flags:

```powershell
scripts\build-windows.ps1 -Clean
scripts\build-windows.ps1 -SkipBinaries
scripts\build-windows.ps1 -SkipZip
```

Current note: the local PowerShell helper looks for Python 3.14, while the
manual commands and GitHub Actions workflow use Python 3.11. Use the manual
build path if your machine does not have Python 3.14 installed.

### Manual PyInstaller Build

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

### GitHub Actions Build

The workflow at `.github/workflows/windows-build.yml` is a manual
`workflow_dispatch` Windows build. It installs dependencies, downloads ffmpeg,
libdiscid, and the VLC runtime, verifies that the VLC backend can be created,
runs PyInstaller, checks that VLC files were packaged, and uploads
`LyonMusicManager-windows.zip` as an artifact.

## Repository Layout

```text
main.py                         Top-level launcher
lyon/__init__.py                App name and version
lyon/app.py                     QApplication setup, splash, and main window launch
lyon/core/cd_detect.py          Windows optical-drive and libdiscid helpers
lyon/core/library.py            SQLite library index and search queries
lyon/core/metadata.py           CTDB, MusicBrainz, and Cover Art Archive lookups
lyon/core/player.py             Playback queue, shuffle, repeat, volume, EQ state
lyon/core/playback_backend.py   libVLC playback backend and Qt Multimedia fallback
lyon/core/ripper.py             ffmpeg-backed CD-to-FLAC worker
lyon/core/settings.py           Settings defaults, persistence, bin lookup
lyon/core/tagger.py             FLAC/Vorbis comment and cover-art writer
lyon/ui/branding.py             Vintage robot app icon and startup splash drawing
lyon/ui/                        Main window, tabs, dialogs, styles, widgets
docs/brand/                     README branding artwork
build/lyon.spec                 PyInstaller build definition
docs/BUILD.md                   Windows build guide
scripts/build-windows.ps1       End-to-end Windows build script
scripts/README.md               Build-script documentation
tests/                          Unit tests for metadata and supporting behavior
requirements.txt                Python runtime dependencies
```

## Testing

The test suite uses `pytest`. Install it in your development environment if it
is not already present:

```cmd
pip install pytest
pytest
```

Current automated coverage includes MusicBrainz multi-disc metadata selection,
CTDB-first lookup fallback behavior, ripper command construction, library query
behavior, library-view tooltip formatting, and player equalizer normalization.
More coverage should be added around full library scanning, playback queue
behavior, rip overwrite/cancel flows, and branding startup as those areas
continue to settle.

## Troubleshooting

- **`ffmpeg not found` while ripping**: place `bin\ffmpeg.exe` in the project
  root or install ffmpeg on `PATH`.
- **No CD drive appears**: CD detection is Windows-only and relies on the Win32
  optical-drive APIs plus libdiscid. Confirm the drive is visible to Windows and
  contains an audio CD.
- **Disc metadata does not resolve**: confirm internet access and set a real
  MusicBrainz contact string in Settings. MusicBrainz may rate-limit generic or
  abusive clients.
- **YouTube tab says WebEngine is unavailable**: install `PySide6-Addons` into
  the active environment and restart the app.
- **Equalizer controls move but audio does not change**: confirm `python-vlc` is
  installed and a 64-bit VLC runtime is either installed system-wide or present
  under `bin\vlc\` with `libvlc.dll`, `libvlccore.dll`, and `plugins\`.
- **Built zip does not run on another machine**: distribute the complete
  `dist\LyonMusicManager\` folder or the generated zip, not just
  `LyonMusicManager.exe`.

## Credits And Third-Party Services

Lyon Music Manager uses MusicBrainz metadata, Cover Art Archive artwork,
ffmpeg/libcdio for CD audio extraction, libdiscid for disc IDs, libVLC for
local playback and equalizer support, Mutagen for tag handling, and Qt/PySide6
for the desktop UI. Respect the MusicBrainz access
policy by setting an appropriate contact value before distributing builds.
