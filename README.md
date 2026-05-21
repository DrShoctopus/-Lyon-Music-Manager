<p align="center">
  <img src="docs/brand/lyon-splash.png" alt="Sea Lyon Media Manager" width="100%">
</p>

# Sea Lyon Media Manager

Sea Lyon Media Manager is a Windows focused desktop media manager for local music,
podcasts, internet radio, audio CD ripping, video playback, YouTube search/download, and library
organization. It is written in Python with PySide6 and uses SQLite, Mutagen,
libVLC, ffmpeg, yt-dlp, CUETools DB, MusicBrainz, TheAudioDB, Cover Art Archive,
LRCLIB and libdiscid.

The app is optimized for Windows 10/11 because CD drive detection, libdiscid,
and CD ripping are Windows-centered workflows. Most library, playback, video,
YouTube downloading, and UI work can still be developed on macOS or Linux when they're required

Python packages and native runtimes are available.

Current application version: `0.6.0` in `lyon/__init__.py`.

## Status

`LMM-DEV` is an active development branch. The repository is ready to run from
source, includes an automated test suite, and contains Windows packaging support
through PyInstaller plus a manual GitHub Actions workflow.

This is not yet a polished public installer repository. Treat it as an app
source tree with build automation, runtime diagnostics, and checked-in brand
assets.

## Feature Overview

### App Shell

- Dark Windows Media Player-inspired PySide6 desktop UI.
- Sea lion app icon, startup splash, and README banner assets under
  `docs/brand/`.
- First-run setup for music roots and library folders.
- Runtime diagnostics for ffmpeg, libdiscid/discid, VLC/libVLC, Python
  packages, and related runtime paths.
- Persistent Settings dialog for library paths, ripping, metadata providers,
  YouTube download defaults, playback, equalizer, and about documentation.

### Library Management

- SQLite-backed library at the user's app-data location.
- Scans audio files: `.flac`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wav`,
  `.aiff`, `.aif`, and `.wma`.
- Scans video files: `.mp4`, `.mkv`, `.webm`, `.avi`, and `.mov`.
- Reads audio/container metadata with Mutagen.
- Browse by genre, artist, album, track, playlists, and virtual collections.
- Search across title, artist, album artist, album, and display fallbacks.
- List, simple, and grid-oriented library views.
- Add folders, watch saved roots for changes, incrementally rescan, remove
  missing files, and drag/drop media.
- Manual and smart playlists, playlist export to M3U, and queue-to-playlist save.
- Track ratings, liked tracks, play count, recently played, most played, and top
  rated views.
- Duplicate-track finder that removes library records without deleting files.
- Metadata editing, batch metadata editing, and MusicBrainz metadata fetch for
  existing albums.

### Music Playback

- libVLC-backed local audio playback.
- Queue restore on startup, enqueue, reorder, remove, previous/next, seek, stop,
  volume, mute, shuffle, repeat all, and repeat one.
- Persistent bottom transport and Now Playing view.
- Crossfade support with configurable overlap.
- Sleep timer from the main toolbar.
- macOS media-key hook when the optional platform support is available.
- Playback-unavailable fallback so the app can still open when VLC/libVLC is
  missing.

### Podcasts And Radio

- First-class Podcasts tab for saved RSS/Atom podcast feeds.
- Add individual podcast feeds or import OPML subscription lists.
- Background podcast refresh with searchable episode catalog.
- Podcast episode playback uses the same libVLC stream pipeline as the main
  audio player.
- Internet Radio tab for saved live streams and imported M3U/PLS playlists.

### Equalizer And Now Playing

- 10-band libVLC equalizer with preamp.
- Built-in curves, flat reset, custom saved curves, and live preview while
  sliders move.
- Equalizer settings apply to both audio playback and video playback.
- Now Playing cover art, blurred background, format strip, rating control, queue
  preview, album info, and synced/plain lyrics.
- Lyrics lookup order: `.lrc` sidecar, embedded tags, then LRCLIB when enabled.
- In-memory lyrics cache is capped to avoid unbounded growth.

### CD Detection, Metadata, And Ripping

- Windows optical-drive detection through Win32 APIs.
- libdiscid support for MusicBrainz disc IDs and table-of-contents data.
- CUETools DB-compatible TOC reading through Windows APIs.
- Duplicate disc detection by saved disc ID, with automatic eject notification.
- Metadata provider order for discs: CUETools DB first, then MusicBrainz, then
  TheAudioDB enrichment where useful.
- Artwork from Cover Art Archive, CUETools DB metadata URLs, and TheAudioDB.
- ffmpeg/libcdio ripping when available.
- Windows raw CD-DA reader fallback when ffmpeg lacks libcdio support.
- Output formats: FLAC, MP3, AAC/M4A, Opus, OGG Vorbis, ALAC, WAV, AIFF, and
  WMA.
- FLAC compression and lossy bitrate settings.
- Organized output under `<Artist>/<Year> - <Album>/<Track> - <Title>.<ext>`.
- Unknown-album rips get numbered folders to avoid accidental overwrites.
- Per-track progress, cancellation, retry failed tracks, failure logs, Mutagen
  tag writing, embedded cover art, optional eject after rip, and library import
  after each completed track.
- Optional CUETools DB AccurateRip v1 verification for FLAC rips.

### Video

- libVLC video player tab with local video catalog sidebar.
- Optical **Disc** tab for Windows-first Audio CD playback plus DVD/VCD launch
  through the VLC video player.
- Thumbnail cards from library artwork or yt-dlp sidecar images.
- Open file, play/pause/stop, seek, volume, mute, and playback rate from
  0.25x to 2x.
- Audio-track and subtitle-track selection.
- External subtitle loading.
- PNG/JPEG snapshots through libVLC.
- Fullscreen mode with keyboard controls and OSD feedback.
- Video playback pauses automatically when leaving the Video tab.

### YouTube

- Native Qt YouTube search tab backed by yt-dlp search; no WebEngine page is
  required.
- Result list with thumbnails, duration, channel, view count, and click-to-
  download.
- Download dialog for audio-only or video downloads.
- Audio formats: FLAC and MP3.
- Video formats: MP4, MKV, and WebM.
- Optional playlist downloads.
- yt-dlp progress log and automatic library import for completed files.
- ffmpeg is used for extraction, merging, thumbnails, metadata, and subtitles
  when available.

## Requirements

### Python Runtime

- Python 3.11+ 64-bit is the recommended development/runtime target.
- Install pinned runtime packages from `requirements.txt`:

```cmd
pip install -r requirements.txt
```

Pinned runtime packages currently include:

- `PySide6-Essentials` for the Qt desktop runtime.
- `mutagen` for media tag reading/writing.
- `musicbrainzngs`, `requests`, and `defusedxml` for metadata lookups.
- `python-vlc` for audio/video playback and audible equalizer support.
- `discid` on Windows for MusicBrainz disc IDs.
- `yt-dlp` for YouTube search and downloads.
- `watchdog` for recursive library-folder monitoring.

Build machines should install `requirements-build.txt`, which layers
PyInstaller and build-only icon tooling on top of the runtime dependencies.

### Native Runtime Files

For full playback, ripping, and CD support, place native binaries in `bin/` at
the repository root:

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

- Some libdiscid archives call the DLL `libdiscid.dll`; the current Windows
  build flow copies it to `bin/discid.dll`.
- ffmpeg should include CDDA/libcdio support when possible. On Windows, Lyon can
  fall back to its raw CD-DA reader if libcdio is unavailable.
- The VLC runtime must match the Python/app architecture. Use 64-bit VLC with
  64-bit Python.
- The app launches without these binaries, but CD detection, ripping, local
  audio playback, video playback, and audible EQ need the relevant runtime.

## Quick Start

### Windows

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Optional but required for full ripping/playback/video support:
:: add ffmpeg.exe, discid.dll, and the VLC runtime under bin\

py main.py
```

### macOS Or Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Non-Windows platforms are useful for UI, library, YouTube, and much of playback
development. CD-drive features are intentionally Windows-specific.

## Data Locations

User data lives outside the repository:

- Windows: `%APPDATA%\LyonMusicManager\`
- macOS/Linux: `$XDG_CONFIG_HOME/LyonMusicManager/` or
  `~/.config/LyonMusicManager/`

Important files:

- `settings.json` stores app preferences.
- `library.db` stores the SQLite media index.
- `metadata-diagnostics.log` is created only when metadata diagnostics are
  enabled.

Ripped music defaults to `Music\Lyon` under the current user, and YouTube
downloads default to `<music_root>\YouTube` unless changed in Settings.

## Using The App

1. Start with `py main.py` on Windows or `python main.py` on other platforms.
2. Complete first-run setup, choose a music root, and add existing library
   folders.
3. Use **Library** to scan, browse, search, rate, like, edit metadata, create
   playlists, and play tracks.
4. Use the bottom transport or **Now Playing** for playback, queue, ratings,
   lyrics, shuffle/repeat, seek, volume, and track info.
5. Use **EQ** for the 10-band equalizer, preamp, presets, and custom curves.
6. Use **Disc** on Windows for Audio CD playback through the queue/transport,
   or to open DVD/VCD media through the VLC video player.
7. Use **Rip** on Windows after adding ffmpeg and libdiscid/VLC runtime files.
8. Use **Video** for local video playback, fullscreen, subtitles, screenshots,
   and catalog browsing.
9. Use **YouTube** to search with yt-dlp and download audio or video into the
   configured output folder.
10. Use **Help > Runtime Diagnostics** when a native dependency is missing or a
   packaged build behaves differently from a source run.

## Repository Layout

```text
main.py                         Top-level launcher
lyon/__init__.py                App name and version
lyon/app.py                     QApplication setup, splash, and main window
lyon/core/cd_detect.py          Windows CD-drive, TOC, libdiscid, eject helpers
lyon/core/ctdb_lookup.py        CUETools DB metadata helpers
lyon/core/ctdb_verify.py        AccurateRip v1 verification against CTDB
lyon/core/diagnostics.py        Runtime dependency checks
lyon/core/equalizer.py          10-band EQ limits and presets
lyon/core/library.py            SQLite media library and playlist queries
lyon/core/media_keys.py         Optional macOS media-key integration
lyon/core/metadata.py           CTDB, MusicBrainz, TheAudioDB, artwork lookups
lyon/core/player.py             Audio queue, transport, crossfade, EQ state
lyon/core/playback_backend.py   libVLC audio backend and fallback backend
lyon/core/ripper.py             ffmpeg/raw-CDDA ripping worker
lyon/core/settings.py           Settings model, persistence, bundled-bin paths
lyon/core/smart_playlist.py     Smart playlist rules and SQL conversion
lyon/core/tagger.py             Mutagen tag and artwork writing
lyon/core/vlc_equalizer.py      Shared libVLC equalizer controller
lyon/core/yt_downloader.py      yt-dlp download worker
lyon/ui/                        Main window, views, dialogs, widgets, theme
docs/brand/                     Checked-in brand assets
docs/reviews/                   Historical engineering review notes
docs/BUILD.md                   Windows build guide
docs/VLC_PLAYBACK_CHECKLIST.md  VLC playback setup checklist
build/lyon.spec                 PyInstaller spec
build/lyon.iss                  Inno Setup script
scripts/build-windows.ps1       Windows build automation
scripts/README.md               Build-script notes
tests/                          Pytest suite
requirements.txt                Python runtime dependencies
```

## Testing

Install pytest in the active environment if needed:

```cmd
pip install pytest
pytest
```

Useful narrower checks:

```cmd
python -m compileall -q main.py lyon tests
pytest tests/test_player_equalizer.py
pytest tests/test_ripper.py tests/test_ctdb_verify.py
pytest tests/test_main_window_integration.py
```

Current coverage includes settings, dialogs, library queries, smart playlists,
metadata provider fallbacks, CUETools DB lookup and verification, ripping
command/failure paths, CD detection helpers, playback backend fallback,
equalizer behavior, transport, Now Playing lyrics cache, video player handoff,
branding, accessibility, UI dependencies, and packaging checks.

## Resource Lifecycle Notes

The app uses long-lived native and background resources. The current codebase
intentionally closes or bounds them:

- SQLite connections are closed from `MainWindow.closeEvent`.
- Shared metadata HTTP sessions and diagnostics file handlers are closed from
  `metadata.shutdown()`.
- libVLC audio/video players and instances are released during shutdown.
- Windows DLL-directory handles for libdiscid and VLC are retained while needed
  and closed on app exit.
- Ripper, YouTube search/download, metadata fetch, and library scan workers are
  joined or cleaned up before their owning UI is destroyed.
- Video thumbnail and lyrics caches are capped.
- YouTube thumbnail network replies are cancelled when results are replaced or
  the YouTube view shuts down.

The May 17, 2026 memory/resource review fixed remaining Qt ownership leaks in
crossfade backends/timers, transient dialogs, context menus, metadata-fetch
workers, YouTube thumbnail replies, and fullscreen video windows.

## Windows Builds

### Recommended Script

Run from PowerShell at the repository root:

```powershell
scripts\build-windows.ps1
```

The script creates `.venv`, installs dependencies and PyInstaller, downloads
missing ffmpeg/libdiscid/VLC runtime files, smoke-tests imports plus VLC backend
creation, runs PyInstaller, and writes:

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
will not work because the app needs bundled Python, Qt, DLL, and plugin files.

See `docs/BUILD.md` for the longer build guide.

### GitHub Actions

`.github/workflows/windows-build.yml` is a manual `workflow_dispatch` build. It
installs dependencies, downloads ffmpeg/libdiscid/VLC runtime files, validates
build inputs, smoke-tests the VLC playback backend, builds with PyInstaller,
verifies packaged VLC files, zips `dist\LyonMusicManager\`, and uploads the zip
artifact.

## Troubleshooting

- **Audio playback is unavailable**: run Runtime Diagnostics. Confirm
  `python-vlc` is installed and a 64-bit VLC runtime is discoverable or present
  under `bin\vlc\`.
- **Video player shows the unavailable screen**: fix the same VLC/libVLC setup
  used for audio playback and EQ.
- **Equalizer controls move but sound does not change**: the audible EQ requires
  libVLC, not just the Qt UI.
- **`ffmpeg not found` while ripping or downloading audio**: place
  `bin\ffmpeg.exe` in the repo root or install ffmpeg on `PATH`.
- **No CD drive appears**: CD detection is Windows-only. Confirm Windows sees
  the optical drive and that an audio CD is inserted.
- **Disc metadata does not resolve**: keep CUETools DB metadata lookup enabled,
  confirm internet access, and set a real MusicBrainz contact value before
  heavy lookup use.
- **YouTube search/download fails**: confirm `yt-dlp` is installed in the active
  environment. ffmpeg is also needed for high-quality video merging and audio
  conversion.
- **Built zip fails on another machine**: distribute the complete generated
  folder or zip, not just `LyonMusicManager.exe`.

## Credits And Services

Sea Lyon Media Manager uses Qt/PySide6, libVLC, ffmpeg/libcdio, libdiscid,
CUETools DB, MusicBrainz, TheAudioDB, Cover Art Archive, yt-dlp, Mutagen,
requests, and defusedxml. Respect MusicBrainz access policies by setting
an appropriate app/contact value before distributing builds or performing heavy
metadata lookups.
