# macOS Apple Silicon Readiness Report

Date: 2026-05-27

Scope: code and workflow review only. This report is based on repository state, automated tests, build scripts, and runtime code paths. It does not rely on the implementation plan as proof of readiness.

## Verdict

Status: code-ready for a signed macOS CI build and hardware QA, but not release-certified until the macOS GitHub Actions workflow completes on an Apple Silicon runner and the optical-drive scenarios are exercised on physical hardware.

No code-level blocker remains from the review findings. The remaining readiness gates are operational: Apple signing/notarization secrets, successful vendor binary fetch/build, successful `.app` and `.dmg` production, and physical optical-drive validation.

## Code Readiness Evidence

### Platform Isolation

- macOS-specific branches are guarded by `sys.platform == "darwin"` in `lyon/app.py`, `lyon/core/settings.py`, `lyon/core/cd_detect.py`, `lyon/core/playback_backend.py`, `lyon/ui/main_window.py`, and related disc/playback helpers.
- Windows CD detection and MCI eject behavior remain behind `sys.platform == "win32"` in `lyon/core/cd_detect.py`.
- Non-macOS platforms do not import PyObjC-only modules at module import time. `lyon/core/disc_macos.py` imports PyObjC inside macOS-only helper calls.

Readiness: pass at code level.

### macOS App Data and Launch Behavior

- `app_data_dir()` writes macOS settings under `~/Library/Application Support/LyonMusicManager`.
- `migrate_macos_app_data()` moves the legacy `~/.config/LyonMusicManager` directory before settings load.
- macOS uses `.AppleSystemUIFont` and opens the main window at natural size instead of maximized.

Readiness: pass at code level.

### Bundled Runtime Discovery

- `bundled_bin_dir()` resolves frozen macOS executables under `Contents/MacOS/bin`.
- `bundled_frameworks_dir()` resolves `Contents/Frameworks`.
- VLC runtime discovery prefers bundled `Contents/Frameworks/libvlc.dylib` and plugin paths before falling back to `/Applications/VLC.app`.
- `cd_detect` preloads bundled `libdiscid.0.dylib` from `Contents/Frameworks` before importing `discid`.

Readiness: pass at code level.

### Dependencies

- `requirements.in` includes `discid` for macOS and resolvable PyObjC packages needed by the current code: `pyobjc-framework-Cocoa` and `pyobjc-framework-DiskArbitration`.
- `requirements.txt` and `requirements-build.txt` have been regenerated and now include macOS `discid`, PyObjC core, Cocoa, and DiskArbitration entries.
- The invalid `pyobjc-framework-IOKit` dependency was removed; IOKit is loaded dynamically via `objc.loadBundle`.

Readiness: pass at code level.

### Optical Disc Detection, Playback, and Eject

- macOS drive enumeration uses IOKit first and falls back to `diskutil`.
- Audio-disc checks use `diskutil info`.
- CDDA playback builds `cdda:///dev/diskN` MRLs for macOS device paths.
- Disc and Rip tabs are hidden on macOS until an optical drive is present, with a polling watcher for drive changes.
- Eject now targets the selected `/dev/diskN` via `diskutil eject`, avoiding global tray eject behavior.

Readiness: code path present, hardware validation required.

### Packaging and Architecture Enforcement

- macOS CI uses `macos-14`, `actions/setup-python` with `architecture: arm64`, and explicit host/Python arm64 assertions.
- PyInstaller is invoked with `--target-arch arm64`.
- The bundle script stages ffmpeg, fpcalc, VLC, plugins, and libdiscid inside the `.app`.
- The bundle script thins Mach-O files to arm64 and fails the build if any Mach-O file is not exactly `arm64`.
- `build/lyon.spec` sets `LSMinimumSystemVersion` to `11.0`.
- DMG naming includes `-arm64`.

Readiness: pass at code level, CI execution required.

### Signing, Notarization, and DMG

- Scripts exist to import the Developer ID certificate, codesign the bundle, notarize/staple the `.app`, create a DMG, sign the DMG, notarize it, and staple it.
- These steps depend on GitHub secrets and Apple notary availability.

Readiness: implementation present, operational validation required.

### Updater and Appcast

- Appcast parsing selects enclosures by `sparkle:os`.
- macOS no longer treats a Windows-only `.exe` enclosure as a disk-image download.
- `scripts/generate-appcast.py` can emit both Windows and macOS enclosures.
- The macOS release workflow waits for the Windows installer asset, regenerates a multi-OS `appcast.xml`, and uploads it with `--clobber`.

Readiness: pass at code level.

### Diagnostics

- Diagnostics now check macOS `Contents/Frameworks` for `libdiscid.0.dylib` and VLC runtime files.
- User-facing ripper errors now name `Contents/Frameworks/libdiscid.0.dylib` on macOS and keep the existing Windows DLL guidance on Windows.

Readiness: pass at code level.

## Automated Verification

Commands run on this tree:

```text
.venv/bin/python -m pytest -q
801 passed, 2 skipped in 60.77s

git diff --check
exit code 0
```

New regression coverage includes:

- macOS dependency lockfile coverage.
- macOS appcast enclosure selection and Windows-installer rejection.
- macOS release workflow multi-OS appcast generation.
- macOS diagnostics for `Contents/Frameworks`.
- selected-device optical-drive eject behavior.

## Remaining Release Gates

1. Run `.github/workflows/macos-build.yml` on a tag or manual dispatch with all Apple secrets configured.
2. Confirm the workflow produces `SeaLyonMediaManager-<version>-arm64.dmg`.
3. Confirm bundle verification reports every Mach-O file as exactly `arm64`.
4. Confirm codesign, notarization, and stapling succeed for both `.app` and `.dmg`.
5. Run the app on Apple Silicon with no optical drive and confirm Disc/Rip tabs are hidden.
6. Plug in a supported external optical drive and confirm Disc/Rip tabs appear.
7. Read an audio CD, fetch metadata, play via VLC CDDA MRL, rip with ffmpeg, and eject the selected drive.
8. Publish a release draft and verify the final `appcast.xml` contains both Windows and macOS enclosures.

## Risk Notes

- Physical optical-disc behavior cannot be fully proven by unit tests because it depends on IOKit, DiskArbitration/diskutil behavior, real USB drives, and real media.
- The macOS workflow now waits for the Windows installer asset before publishing the multi-OS appcast. A failed Windows release build will intentionally prevent macOS from publishing a partial appcast.
- The build scripts rely on external vendor downloads for VLC, ffmpeg, fpcalc, and libdiscid source. CI cache or upstream availability can affect build repeatability.
