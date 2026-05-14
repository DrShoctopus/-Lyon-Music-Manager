<p align="center">
  <img src="docs/brand/lyon-splash.png" alt="Lyon Media Manager sea lion splash" width="100%">
</p>

# Lyon Media Manager

Lyon Media Manager is a Windows-focused desktop media app for ripping audio CDs
to a choice of lossless or lossy formats, organizing a local music library,
playing tracks and video files, downloading from YouTube, and browsing YouTube
from one Windows Media Player-inspired interface.

The app is built with Python, PySide6, Qt Multimedia, Qt WebEngine, SQLite,
Mutagen, MusicBrainz, TheAudioDB, CUETools DB, Cover Art Archive, ffmpeg,
libdiscid, libVLC, and yt-dlp.

## Current Status

`LMM-DEV` is an active desktop application branch. It includes the core music
library, playback, CD-ripping, YouTube browsing and downloading, a video player,
and sea lion branding. The app can be run from source for development, and
Windows packaging is available through PyInstaller and a manual GitHub Actions
workflow.

This is still source-first rather than a polished public installer repository.
The app is optimized for Windows 10/11 because CD-drive detection, libdiscid,
and audio-CD ripping are Windows-specific. Most UI and library behavior can
still be developed on other platforms where PySide6 is available.

The application version is defined in `lyon/__init__.py` (currently `0.5.0`).

## Current Capabilities

- **Sea lion startup branding** using checked-in app icon and splash screen
  images from `docs/brand/`.
- **Windows Media Player-style shell** with a dark glossy theme, tabbed
  navigation, status messages, Settings access, and a persistent transport bar.
- **First-run setup and runtime diagnostics** to choose core folders and check
  ffmpeg, libdiscid/discid, VLC/libVLC, and Qt WebEngine availability.
- **Library management** backed by SQLite in the user's app-data directory. The
  scanner imports `.flac`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wav`, and
  `.wma` files and reads tags with Mutagen.
- **Library folder management** from Settings for reviewing and changing the
  folders Lyon scans.
- **Library browsing and search** by artist, album, and track, including
  fallbacks for blank metadata such as `Unknown Artist` and `Unknown Album`.
- **Playback queue** with a libVLC-backed local-audio engine and Qt Multimedia
  fallback, including play/pause, previous, next, seek/scrub, volume, mute,
  shuffle, repeat-all, repeat-one, enqueue, an editable Queue dialog, playback
  shortcuts, and a Now Playing view with cover art.
- **Library playback polish** including enqueue feedback, current-track
  highlighting, selected-track scrolling, and track tooltips with artist, album,
  time, and file type.
- **Six-band equalizer** with five built-in presets and full manual control.
  Persisted settings are applied to libVLC playback; the Qt Multimedia fallback
  keeps the controls available but plays audio flat.
- **Audio CD detection** on Windows using Win32 optical-drive APIs and
  libdiscid, with duplicate-disc detection and an automatic eject notification
  when the same disc is inserted twice.
- **CUETools DB Metadata Plugin-style lookup** as the primary disc metadata
  source, with MusicBrainz and TheAudioDB fallbacks.
- **CUETools DB audio verification** after ripping — each track's AccurateRip
  v1 CRC is compared against the CTDB database to confirm a bit-perfect rip.
- **Cover Art Archive, CUETools DB, and TheAudioDB artwork support** when cover
  downloads are enabled.
- **Multi-format CD ripping** through ffmpeg/libcdio with per-track output,
  selectable output format (FLAC, MP3, AAC/M4A, Opus, OGG Vorbis, ALAC, WAV,
  AIFF, WMA), format-specific quality settings, Mutagen tag writing, embedded
  cover art, overwrite confirmation, cancellation, and optional disc eject after
  a successful rip.
- **Automatic rip organization** under the configured music root using
  `<Artist>/<Year> - <Album>/<Track> - <Title>.<ext>`, with repeated unknown
  album rips placed into numbered folders to avoid overwriting earlier unknown
  discs.
- **Video player tab** backed by libVLC with hardware-accelerated rendering,
  a real-time seek bar, per-media volume and mute, variable playback rate
  (0.25×–2×), multi-track audio selection, subtitle track selection and external
  subtitle loading, one-click PNG/JPEG screenshots, fullscreen mode, and a
  collapsible video catalog sidebar with thumbnail cards.
- **In-app YouTube tab** using Qt WebEngine when `PySide6-Addons` is installed,
  with search/URL navigation and automatic video pause when leaving the tab.
- **YouTube download** via yt-dlp with selectable audio-only or video+audio
  output, format and quality options, and a unified save location configured in
  Settings.
- **Tabbed Settings dialog** covering Library paths, CD Ripping format and
  quality, Metadata sources and API keys, YouTube download options, and About /
  Donate information.
- **Windows packaging** through PyInstaller, plus a PowerShell build script and
  a manual GitHub Actions workflow that can produce a distributable zip.

## Requirements

### Runtime Python Packages

Install the packages from `requirements.txt`:

- `PySide6` for the desktop UI and multimedia playback.
- `PySide6-Addons` for the optional Qt WebEngine YouTube tab.
- `mutagen` for reading and writing audio tags.
- `musicbrainzngs` and `requests` for metadata and artwork lookup.
- `defusedxml` for safe XML parsing of metadata responses.
- `Pillow` for image handling.
- `python-vlc` for the preferred local playback and video backend and audible equalizer.
- `discid` on Windows for MusicBrainz disc IDs.
- `yt-dlp` for YouTube audio and video downloading.

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
  six-band EQ will not audibly affect playback and video playback will not be
  available.
- The app can still launch without these files, but CD detection, ripping, and
  video playback will not be functional.

## Quick Start From Source

On Windows PowerShell or `cmd.exe` from the project root:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Optional for playback EQ, ripping, and video — required for a fully functional app:
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
   - The sea lion splash appears briefly before the main window opens.

2. **Configure settings**
   - Open **Settings**.
   - Choose the music root. The default is `Music\Lyon` under the current user.
   - Set the rip output format and quality on the **CD Ripping** tab.
   - Optionally set a default CD drive such as `D:`.
   - Keep **Use CUETools DB Metadata Plugin lookup** enabled to make CUETools DB
     the primary disc metadata source.
   - Update the MusicBrainz contact value before redistributing or doing heavy
     metadata lookups.
   - TheAudioDB defaults to the documented free API key, but Settings allows a
     custom key.
   - Set the YouTube download folder on the **YouTube** tab.

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
   - Open **6 Band EQ** to enable, choose a preset, and adjust the persisted
     equalizer curve.

5. **Rip a CD**
   - Put `ffmpeg.exe` and `discid.dll` in `bin/` first.
   - Insert an audio CD and open **Rip**.
   - Click **Refresh Drives** if needed, then **Read Disc**.
   - Review or edit artist, album, year, and track titles.
   - Click **Search Online** if automatic metadata needs correction.
   - Click **Rip CD**. Output is written in the configured format under the
     configured music root and is added to the library after each track
     completes. A CUETools DB verification result is shown for each track.

6. **Play video files**
   - Open **Video**.
   - Use the **Library** sidebar to browse and open local video files.
   - Control playback rate, audio track, and subtitles from the toolbar.
   - Use the fullscreen button or press F for fullscreen mode.
   - Click the camera icon to save a screenshot.

7. **Browse or download from YouTube**
   - Open **YouTube**.
   - Search from the address field or paste a URL.
   - Use the download button to save audio or video via yt-dlp.
   - When leaving the tab, the app pauses page video elements.

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
lyon/core/ctdb_lookup.py        CUETools DB disc metadata lookup
lyon/core/ctdb_verify.py        AccurateRip v1 CRC verification against CUETools DB
lyon/core/diagnostics.py        Runtime dependency checks and diagnostic logging
lyon/core/equalizer.py          Six-band EQ state and preset definitions
lyon/core/library.py            SQLite library index and search queries
lyon/core/metadata.py           CUETools DB, MusicBrainz, TheAudioDB, and artwork lookups
lyon/core/player.py             Playback queue, shuffle, repeat, volume, EQ state
lyon/core/playback_backend.py   libVLC playback backend and Qt Multimedia fallback
lyon/core/ripper.py             ffmpeg-backed multi-format CD-to-audio worker
lyon/core/settings.py           Settings defaults, persistence, bin lookup
lyon/core/tagger.py             Audio tag and cover-art writer (Mutagen)
lyon/core/yt_downloader.py      yt-dlp download worker thread
lyon/ui/branding.py             Sea lion app icon and startup splash image loading
lyon/ui/video_player_view.py    libVLC video player tab with catalog sidebar
lyon/ui/youtube_view.py         Qt WebEngine YouTube tab
lyon/ui/yt_download_dialog.py   YouTube download dialog
lyon/ui/                        Main window, tabs, dialogs, styles, widgets
docs/brand/                     App icon and splash branding artwork
build/lyon.spec                 PyInstaller build definition
docs/BUILD.md                   Windows build guide
scripts/build-windows.ps1       End-to-end Windows build script
scripts/README.md               Build-script documentation
tests/                          Unit tests
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
CUETools DB-first lookup fallback behavior, CUETools DB namespace metadata,
CUETools DB TOC layout and fuzzy fallback, CUETools DB audio verification,
TheAudioDB fallback mapping, ripper command construction, library query
behavior, library-view tooltip formatting, player equalizer normalization,
equalizer presets and settings, settings dialog behavior, diagnostics, branding
startup, and CD detection helpers.

## Troubleshooting

- **`ffmpeg not found` while ripping**: place `bin\ffmpeg.exe` in the project
  root or install ffmpeg on `PATH`.
- **No CD drive appears**: CD detection is Windows-only and relies on the Win32
  optical-drive APIs plus libdiscid. Confirm the drive is visible to Windows and
  contains an audio CD.
- **Disc metadata does not resolve**: keep CUETools DB metadata lookup enabled,
  confirm internet access, and set a real MusicBrainz contact string in
  Settings. MusicBrainz may rate-limit generic or abusive clients.
- **YouTube tab says WebEngine is unavailable**: install `PySide6-Addons` into
  the active environment and restart the app.
- **Equalizer controls move but audio does not change**: confirm `python-vlc` is
  installed and a 64-bit VLC runtime is either installed system-wide or present
  under `bin\vlc\` with `libvlc.dll`, `libvlccore.dll`, and `plugins\`.
- **Video player shows an error screen**: the video tab requires libVLC. See the
  EQ troubleshooting entry above for setup instructions.
- **Built zip does not run on another machine**: distribute the complete
  `dist\LyonMusicManager\` folder or the generated zip, not just
  `LyonMusicManager.exe`.

## Credits And Third-Party Services

Lyon Media Manager uses CUETools DB and MusicBrainz metadata, TheAudioDB album
metadata and artwork, Cover Art Archive artwork, ffmpeg/libcdio for CD audio
extraction, libdiscid for disc IDs, libVLC for local audio/video playback and
equalizer support, yt-dlp for YouTube downloading, Mutagen for tag handling, and
Qt/PySide6 for the desktop UI. Respect the MusicBrainz access policy by setting
an appropriate contact value before distributing builds.
