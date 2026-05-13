# Manual Windows VLC Playback Checklist

Use this checklist after changing playback code or packaging the app with a VLC
runtime.

## Source run

- Install dependencies with `pip install -r requirements.txt`.
- Confirm 64-bit VLC is installed or that the VLC runtime directory is on PATH.
- Launch with `py main.py` from the repository root.
- Play MP3, FLAC, WAV, AAC/M4A, OGG/Opus, and WMA tracks if available.
- Confirm play, pause, stop, previous, next, seek, shuffle, and repeat behavior.
- Confirm the position slider and duration label continue updating during each
  track.
- Open **6 Band EQ**, enable it, and make a clearly audible bass or treble
  adjustment while a track is playing.
- Change tracks and confirm the same EQ curve is still audible after the new
  track starts.
- Disable EQ and confirm playback returns to a flat curve.
- Leave the Library tab for YouTube or Rip and confirm local playback stops as
  before.

## Packaged app

- Build with `pyinstaller build\lyon.spec`.
- Run `dist\LyonMusicManager\LyonMusicManager.exe` on a clean Windows machine.
- Repeat the source playback and EQ checks above.
- If EQ is not audible, verify that python-vlc is bundled and that libVLC DLLs
  plus the `plugins` directory are either installed system-wide or bundled and
  discoverable on PATH before app startup.
