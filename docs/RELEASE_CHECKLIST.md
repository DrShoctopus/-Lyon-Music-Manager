# Sea Lyon 1.0 Smoke-Test Checklist

Record the artifact filename, SHA-256, OS version, and tester initials
for every checked platform. Do not publish a platform unless its
required checklist passes.

## Artifact Records

- [ ] Local changelog extraction passed:
- [ ] Local Ruff gate passed:
- [ ] Local pytest collection count:
- [ ] Local full pytest result:
- [ ] Local appcast dry run passed:
- [ ] Windows setup EXE filename:
- [ ] Windows setup EXE SHA-256:
- [ ] Windows portable zip filename:
- [ ] Windows portable zip SHA-256:
- [ ] macOS DMG filename, if shipping:
- [ ] macOS DMG SHA-256, if shipping:
- [ ] Appcast URL verified:

## Windows 10 Clean Install

- [ ] Install `SeaLyonMediaManager-1.0.0-Setup.exe`.
- [ ] SmartScreen guidance is understandable if shown.
- [ ] App launches from Start menu.
- [ ] Help -> About shows `1.0.0`.
- [ ] Help -> Runtime Diagnostics detects bundled ffmpeg, fpcalc,
      libdiscid/discid, and VLC/libVLC.
- [ ] First-run setup completes and saves a music root.
- [ ] Add a library folder and run a scan.
- [ ] Play a local audio track.
- [ ] Seek, pause, resume, next, previous, shuffle, and repeat work.
- [ ] Gapless playback does not skip or double-play after seeking near
      the end of a track.
- [ ] Crossfade plays the next track without dropping the current one.
- [ ] Equalizer preset audibly changes playback.
- [ ] ReplayGain mode can be changed without crashing playback.
- [ ] Open and play a local video.
- [ ] Load external subtitles, change playback rate, and take a snapshot.
- [ ] Internet Radio can add and play a known-good stream.
- [ ] Podcasts can add or refresh a known-good RSS feed.
- [ ] YouTube tab shows the acknowledgement gate on first use.
- [ ] YouTube search runs after acknowledgement.
- [ ] YouTube download dialog opens and respects the EULA warning.
- [ ] Audio CD detection appears when a drive/disc is available.
- [ ] Rip path starts or gives a clear missing-hardware/runtime message.
- [ ] DLNA server can be toggled and diagnostics remain clear.
- [ ] Cast dialog opens without blocking the UI.
- [ ] Help -> Copy Diagnostics to Clipboard redacts tokens.
- [ ] Help -> Check for Updates uses the HTTPS appcast URL.
- [ ] Uninstall prompts before deleting app data and defaults to keeping
      user data.

## Windows 10 Portable Zip

- [ ] Extract `SeaLyonMediaManager-1.0.0-windows.zip` to a user-writable
      folder.
- [ ] Run `LyonMusicManager.exe` from the extracted folder.
- [ ] Help -> About shows `1.0.0`.
- [ ] Help -> Runtime Diagnostics detects bundled ffmpeg, fpcalc,
      libdiscid/discid, and VLC/libVLC.
- [ ] First-run setup completes and saves a music root.
- [ ] Add a library folder and run a scan.
- [ ] Play a local audio track.
- [ ] Open and play a local video.
- [ ] Help -> Check for Updates uses the HTTPS appcast URL.
- [ ] Close and relaunch from the extracted folder; settings and library
      records persist.

## Windows 11 Clean Install

- [ ] Install `SeaLyonMediaManager-1.0.0-Setup.exe`.
- [ ] SmartScreen guidance is understandable if shown.
- [ ] App launches from Start menu.
- [ ] Help -> About shows `1.0.0`.
- [ ] Help -> Runtime Diagnostics detects bundled ffmpeg, fpcalc,
      libdiscid/discid, and VLC/libVLC.
- [ ] First-run setup completes and saves a music root.
- [ ] Add a library folder and run a scan.
- [ ] Play a local audio track.
- [ ] Seek, pause, resume, next, previous, shuffle, and repeat work.
- [ ] Gapless playback does not skip or double-play after seeking near
      the end of a track.
- [ ] Open and play a local video.
- [ ] Internet Radio can add and play a known-good stream.
- [ ] Podcasts can add or refresh a known-good RSS feed.
- [ ] YouTube acknowledgement and search flow works.
- [ ] Help -> Copy Diagnostics to Clipboard redacts tokens.
- [ ] Help -> Check for Updates uses the HTTPS appcast URL.
- [ ] Uninstall data-retention prompt appears and defaults to No.

## Windows 11 Portable Zip

- [ ] Extract `SeaLyonMediaManager-1.0.0-windows.zip` to a user-writable
      folder.
- [ ] Run `LyonMusicManager.exe` from the extracted folder.
- [ ] Help -> About shows `1.0.0`.
- [ ] Help -> Runtime Diagnostics detects bundled ffmpeg, fpcalc,
      libdiscid/discid, and VLC/libVLC.
- [ ] First-run setup completes and saves a music root.
- [ ] Add a library folder and run a scan.
- [ ] Play a local audio track.
- [ ] Open and play a local video.
- [ ] Help -> Check for Updates uses the HTTPS appcast URL.
- [ ] Close and relaunch from the extracted folder; settings and library
      records persist.

## Windows Upgrade Install

- [ ] Install the latest RC.
- [ ] Add a test library and change at least one setting.
- [ ] Install `1.0.0` over the RC.
- [ ] Existing settings are preserved.
- [ ] Existing library database is preserved.
- [ ] Help -> About shows `1.0.0`.
- [ ] Playback and library scan still work after upgrade.
- [ ] Help -> Check for Updates offers `1.0.0` from the RC before
      upgrading, then reports latest after upgrade.

## macOS Apple Silicon

Complete this section only if macOS remains in the 1.0 support surface.

- [ ] Install on the oldest macOS Apple Silicon version advertised for
      the 1.0 release.
- [ ] If the smoke pass does not cover macOS 11 Big Sur, README,
      CHANGELOG, GitHub Release, and appcast wording are narrowed to the
      oldest tested macOS version before publishing.
- [ ] `.github/workflows/macos-build.yml` `MACOS_MINIMUM_SYSTEM_VERSION`
      matches the oldest tested macOS version.
- [ ] DMG opens and app can be dragged to `/Applications`.
- [ ] If signed/notarized, Gatekeeper allows launch without manual
      quarantine removal.
- [ ] If unsigned, release notes and README clearly say so.
- [ ] Help -> About shows `1.0.0`.
- [ ] Help -> Runtime Diagnostics detects bundled ffmpeg, fpcalc,
      libdiscid, and VLC/libVLC.
- [ ] First-run setup completes and saves a music root.
- [ ] Add a library folder and run a scan.
- [ ] Play a local audio track.
- [ ] Seek, pause, resume, next, previous, shuffle, and repeat work.
- [ ] Gapless playback does not skip or double-play after seeking near
      the end of a track.
- [ ] Open and play a local video.
- [ ] Internet Radio can add and play a known-good stream.
- [ ] Podcasts can add or refresh a known-good RSS feed.
- [ ] YouTube acknowledgement and search flow works.
- [ ] Optical drive tabs stay hidden until a drive is detected.
- [ ] Help -> Copy Diagnostics to Clipboard redacts tokens.
- [ ] Help -> Check for Updates offers the macOS DMG enclosure.

## HiDPI And Layout

- [ ] Windows 100% scale smoke pass.
- [ ] Windows 125% scale smoke pass.
- [ ] Windows 150% scale smoke pass.
- [ ] macOS Retina smoke pass, if macOS ships.
- [ ] Main window, Settings, About, Diagnostics, YouTube, Video, and
      Now Playing text does not overlap or clip.
- [ ] See `docs/HIDPI_MATRIX.md` for the detailed screen matrix.

## Final Release Approval

- [ ] All shipped platforms passed their checklist.
- [ ] Failed or deferred platforms are not advertised publicly.
- [ ] SHA-256 manifests match downloaded artifacts.
- [ ] Draft GitHub Release body matches `CHANGELOG.md` `1.0.0`.
- [ ] `appcast.xml` contains only shipped platform enclosures.
- [ ] Privacy, EULA, SmartScreen, and third-party notices links work.
- [ ] Release owner approves publishing.
