# Lyon Music Manager

A Windows desktop app that rips CDs to FLAC, manages your local library,
plays it back, and lets you browse and watch YouTube — all from a single
Spotify-inspired interface.

## What it does

- **Rip CDs to FLAC** with one click. Insert a disc, *Read Disc*, *Rip CD*.
  Files are auto-organised into `Music\Lyon\<Artist>\<Year> - <Album>\` with
  proper tags and embedded cover art.
- **Look up album metadata online** via MusicBrainz (disc-ID identification)
  and Cover Art Archive (artwork). Edit anything before ripping if the match
  isn't quite right, or click *Search Online* to query manually.
- **Manage a local library** with a three-pane artist / album / track
  browser, full-text search, folder import, rescan, and missing-file pruning.
  Backed by a small SQLite database; nothing is uploaded.
- **Play music** with a familiar transport bar — play / pause, skip,
  shuffle, repeat (off / all / one), seek and volume. Includes a full
  Now Playing screen with the queue.
- **Watch YouTube** in an embedded Chromium tab. Real YouTube: search,
  recommendations, sign-in, the full site. (Audio still routes through your
  system, separate from the local-library player.)

## How it looks

Spotify-inspired dark theme:

- Black left sidebar with **Home / Your Library / YouTube / Rip CD**
- `#121212` content area, `#181818` cards (hover `#282828`)
- Spotify green (`#1DB954`) accents on the active sidebar item, primary
  buttons, and slider hover
- Card-based **Home** screen showing all the albums in your library;
  click a card to jump straight to its tracks
- Slim Spotify-style transport bar across the bottom

## Quick start (Windows, from source)

Requires Python 3.11+ (3.13/3.14 work too).

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Drop two binaries into bin\ at the project root for CD ripping:
#   bin\ffmpeg.exe        (Windows static build, gyan.dev)
#   bin\discid.dll        (libdiscid Windows release)

py main.py
```

The YouTube tab needs `PySide6-Addons` (already in `requirements.txt`).
That pulls in QtWebEngine + Chromium, ~150 MB. Without it the YouTube tab
shows a "Not installed" message; everything else still works.

## Building a Windows installer

The default packaging step produces a real installer
(`LyonMusicManager-Setup.exe`) using PyInstaller + Inno Setup. The
installer creates a Start menu shortcut, an optional desktop shortcut,
optional `.flac` association, and a proper uninstaller.

See [docs/BUILD.md](docs/BUILD.md) for the full guide. Short version:

```powershell
py -m pip install pyinstaller
py -m PyInstaller build\lyon.spec
# (Install Inno Setup 6 from https://jrsoftware.org/isinfo.php once.)
& "${env:ProgramFiles(x86)}\Inno Setup 6\iscc.exe" installer\lyon.iss
# Output: installer\Output\LyonMusicManager-Setup.exe
```

Distribute the resulting `LyonMusicManager-Setup.exe` — users
double-click it, click *Next*, and the app is installed.

### Building from macOS or Linux

PyInstaller and Inno Setup both run only on Windows, so a Windows
installer has to be built on Windows. The included GitHub Actions
workflow [`.github/workflows/windows-build.yml`](.github/workflows/windows-build.yml)
runs on `windows-latest`, fetches `ffmpeg.exe` and `libdiscid.dll`, runs
PyInstaller, installs Inno Setup, compiles the installer, and uploads
`LyonMusicManager-Setup.exe` as an artifact on every push. Grab the
artifact from the workflow run page on GitHub.

## Folder layout

```
main.py                  Top-level launcher
lyon/
  app.py                 QApplication entry point + Spotify QSS load
  core/
    library.py           SQLite library + mutagen tag scan
    metadata.py          MusicBrainz + Cover Art Archive lookups
    cd_detect.py         Drive enumeration, libdiscid, eject
    ripper.py            Background CD-to-FLAC worker (ffmpeg)
    tagger.py            FLAC tag writer
    player.py            QMediaPlayer wrapper with queue, shuffle, repeat
    settings.py          User config + bundled-bin path resolution
  ui/
    main_window.py       Sidebar + stack + transport bar
    sidebar.py           Spotify-style left navigation
    home_view.py         Card-grid landing page
    library_view.py      Artist / album / track browser
    youtube_view.py      Embedded QWebEngineView
    ripper_view.py       CD detect + rip flow
    now_playing.py       Now Playing view + bottom transport bar
    settings_dialog.py   Settings dialog
    styles.py            Spotify-inspired QSS
    widgets.py           Cover placeholder, elided label, formatters
build/lyon.spec          PyInstaller spec
installer/lyon.iss       Inno Setup script (produces Setup.exe)
bin/                     ffmpeg.exe + discid.dll (you provide these)
.github/workflows/       Windows installer CI
```

## Tech stack

- **PySide6** + **PySide6-Addons** (QtWebEngine for YouTube)
- **mutagen** for tag reading and FLAC writing
- **musicbrainzngs** + **discid** for disc identification
- **requests** for Cover Art Archive
- **ffmpeg** (bundled) for CDDA → FLAC encoding
- **SQLite** for the library

## Notes

- Audio-CD reading uses libdiscid (Windows DLL) for identification and
  ffmpeg's `libcdio` demuxer for extraction; both binaries must live in
  `bin/` (or be on PATH) for ripping. The Library, Player, and YouTube tabs
  run fine without them.
- The MusicBrainz user-agent is configurable in *Settings*. Please put your
  own contact address (URL or email) there if you redistribute the app —
  it's their access-policy etiquette.
- Embedded YouTube playback uses the official site through Chromium. No
  scraping, no API key, no terms-of-service workarounds.
