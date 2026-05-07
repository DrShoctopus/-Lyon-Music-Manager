# Lyon Music Manager

A Windows 8 / 10 / 11 desktop app that rips CDs to FLAC, builds and manages
your music library, and plays it back through a UI inspired by the legacy
Windows Media Player.

## Features

- **CD ripper**: insert a disc, click *Read Disc*, click *Rip CD*. That's it.
- **Automatic metadata**: MusicBrainz lookup by disc ID, Cover Art Archive for
  album art. Manual edit / re-search if you don't like what was found.
- **Auto-organising library**: rips land in `Music\Lyon\<Artist>\<Year> - <Album>\`
  with proper FLAC tags and embedded cover art.
- **Library manager**: artist / album / track browser, search, add folders,
  rescan, prune missing files.
- **Music player**: queue, shuffle, repeat, volume, scrubbing, full Now Playing
  view with cover art.
- **WMP look**: dark gradient chrome, orange accents, glossy transport bar.

## Quick start (developer / from source)

```cmd
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: Place ffmpeg + libdiscid into bin\ at the project root
::   bin\ffmpeg.exe
::   bin\libdiscid.dll

py main.py
```

## Building a single .exe

See [docs/BUILD.md](docs/BUILD.md). Short version:

```cmd
pip install pyinstaller
pyinstaller build\lyon.spec
:: Output goes to dist\LyonMusicManager\
```

## Folder layout

```
main.py                Top-level launcher
lyon/
  app.py               QApplication entry point
  core/                Settings, library DB, metadata, ripper, player
  ui/                  Main window, tabs, transport bar, dialogs
build/lyon.spec        PyInstaller spec
bin/                   ffmpeg.exe + libdiscid.dll (you provide these)
```

## Notes

- Audio CD reading uses libdiscid for identification and ffmpeg's `libcdio`
  demuxer for sample-accurate extraction; both must be present in `bin/` (or on
  PATH) for ripping to work.
- The MusicBrainz user-agent is configurable in *Settings*; please add your own
  contact address to comply with the MusicBrainz access policy if you
  redistribute this app.
