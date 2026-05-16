# Sea Lyon Media Manager — macOS ARM64 Port Plan

**Goal:** Sea Lyon runs natively on Apple Silicon Macs with full feature parity to the current Windows 10/11 build, including CD ripping via an external USB optical drive.

**Status:** Planning document. No code changes have been made.

**Document version:** 1.0
**Last reviewed:** 2026-05-15

---

## 1. Executive Summary

The macOS port is fundamentally a **build, packaging, and feature-completion** problem rather than a code-rewrite problem. The Python source is already partially macOS-aware:

- [app.py:24](lyon/app.py:24) sets `SF Pro Text` on macOS
- [video_player_view.py:665](lyon/ui/video_player_view.py:665) calls `set_nsobject()` for libVLC video rendering on macOS
- [ripper.py:122-127](lyon/core/ripper.py:122) handles the bare `ffmpeg` binary name on non-Windows
- [diagnostics.py:131](lyon/core/diagnostics.py:131) checks for `libvlc.dylib`
- The libVLC playback path is fully cross-platform

The main work is:

1. **CD ripping support** — the largest unique macOS code addition: `cd_detect.py` is currently Windows-only; needs a parallel macOS implementation. The ffmpeg binary must be rebuilt from source with `libcdio` support.
2. **Build pipeline** — no macOS build target exists yet; needs a PyInstaller `.app` spec and a GitHub Actions workflow.
3. **libVLC bundling** — VLC's macOS framework structure differs from the flat Windows DLL layout.
4. **Code signing and notarization** — required for distribution outside the App Store.

**Total estimated effort:** 23–36 working days (5–7 weeks).

**Strategic note:** Apple Silicon is the entire current Mac lineup. This is a forward-looking investment that expands addressable market.

---

## 2. Hard Constraints

| Constraint | Value | Source |
|---|---|---|
| First macOS version supporting Apple Silicon | **macOS 11.0 Big Sur** (Nov 2020) | Apple platform release notes |
| Recommended `LSMinimumSystemVersion` | **11.0** | Covers all Apple Silicon Macs |
| GitHub Actions ARM64 runner | `macos-14` (M1) or `macos-15` (M1) | GitHub Actions runner image catalog |
| GitHub Actions x86_64 runner | `macos-13` (last Intel) | GitHub Actions runner image catalog |
| Notarization tool | `xcrun notarytool` (replaced `altool` Nov 2023) | Apple Developer documentation |
| Apple Developer Program | $99/year individual, $299/year organization | Apple |
| VLC for macOS ARM64 | Native Apple Silicon build available | VideoLAN downloads |
| PySide6 Apple Silicon wheels | Available from PySide6 6.2+ | PyPI |
| libdiscid macOS support | Available; pre-built or buildable from source | MetaBrainz |

---

## 3. Phase 0 — Spike & Decisions (2–3 days)

**Objective:** prove the three risky dependencies (PySide6 + libVLC + ffmpeg-with-libcdio) all work together on the dev machine before scoping the full port.

### 3.1 Tasks

On the dev Mac (Darwin 25.5.0 ARM64, this machine):

- Create a venv: `python3.11 -m venv .venv && source .venv/bin/activate`
- Install: `pip install -r requirements.txt`
  - Note: the `discid` line in [requirements.txt:5](requirements.txt:5) has `sys_platform == "win32"` — it will be skipped. That's correct for now; we add macOS support in Phase 2.
- Install VLC.app from VideoLAN. This makes `libvlc.dylib` discoverable to `python-vlc`.
- Run the source app: `python main.py`
- Verify: library scan works, FLAC playback through libVLC works, EQ produces an audible change.
- Separately, build a minimal `ffmpeg` with libcdio support on the dev Mac using Homebrew dependencies and source builds. This is the highest-risk technical step; if it does not produce a working binary in 1 day, escalate the CD ripping strategy.

### 3.2 Decision artifact
- Confirm playback works.
- Confirm a libcdio-enabled ffmpeg can be built locally.
- Optionally: confirm an external USB optical drive shows up under `diskutil list` and that `discid.read("/dev/rdiskN")` returns a TOC.

### Exit criterion
Music plays via libVLC with audible EQ on the dev Mac. An ffmpeg-with-libcdio binary has been produced and successfully runs `ffmpeg -formats | grep libcdio`.

---

## 4. Phase 1 — Source-Run Cleanup & macOS Conventions (3–5 days)

**Objective:** the codebase is correct for macOS, not just lacking errors.

### 4.1 macOS application support directory

Current state: [settings.py:32-39](lyon/core/settings.py:32) uses `$XDG_CONFIG_HOME` or `~/.config` as a fallback. On macOS, the conventional location is `~/Library/Application Support/`.

Fix:

```python
def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / "LyonMusicManager"
    p.mkdir(parents=True, exist_ok=True)
    return p
```

**Migration**: any developer who ran the source app on macOS already created `~/.config/LyonMusicManager/`. Add a one-time migration: on `app_data_dir()` first call, if the new path is empty but the legacy `~/.config/LyonMusicManager/` exists, move its contents. Log the migration.

### 4.2 Verify libVLC runtime path logic

[playback_backend.py:37-60](lyon/core/playback_backend.py:37) already does the right thing on macOS:
- `os.add_dll_directory` is guarded with `getattr` — no-op on non-Windows ✓
- `os.environ.setdefault("VLC_PLUGIN_PATH", ...)` is cross-platform ✓
- The `bin/vlc/` folder check is path-agnostic ✓

**No change needed.** The bundling layout will be different (see Phase 3), but the runtime configuration code already works.

### 4.3 Verify diagnostics

[diagnostics.py:131](lyon/core/diagnostics.py:131) already checks for `libvlc.dylib` alongside `libvlc.dll` and `libvlc.so`. No change needed.

### 4.4 Verify subprocess flags

[ripper.py:69](lyon/core/ripper.py:69) and [ctdb_verify.py:39](lyon/core/ctdb_verify.py:39) both gate `subprocess.CREATE_NO_WINDOW` behind `sys.platform == "win32"`. No change needed on macOS.

### 4.5 Smoke-test every non-CD feature

| Feature | Validation |
|---|---|
| App launch | Splash + main window |
| Library scan | Add a folder; tracks appear |
| Local playback | Play FLAC; audio is heard |
| EQ | Move bands; audible difference |
| Volume / mute | Slider works |
| Video playback | Open a video; `set_nsobject` renders into the widget |
| MusicBrainz lookup | Search and apply metadata |
| Tagging | Edit metadata; mutagen writes tags |
| YouTube search | yt-dlp returns results |
| YouTube audio download | FLAC produced |
| YouTube video download | MP4 produced (requires ffmpeg) |
| Settings persistence | Quit, relaunch, settings preserved |
| Runtime diagnostics | Dialog shows expected status |

### Exit criterion
Every non-CD feature works from source on macOS ARM64. CD-related features still show the existing "disabled on this platform" message.

---

## 5. Phase 2 — CD Ripping Support (8–12 days)

**Objective:** full CD detection + ripping + verification on macOS with an external USB optical drive.

This is the largest unique macOS code addition. Three parallel sub-tracks (a, b, c) and a verification track (d).

### 5.1 Sub-track 2a — `cd_detect.py` macOS implementation (3–4 days)

Add a parallel macOS code path alongside the existing Windows code. The current module structure (typed dataclasses, helper functions, public surface) does not need to change — only the platform-gated bodies.

**Public API to keep stable:**
- `list_cd_drives() -> list[str]`
- `has_audio_cd(drive: str) -> bool`
- `read_disc(drive: str | None) -> DiscToc | None`
- `eject(drive: str) -> None`

**macOS implementations:**

```python
# list_cd_drives() on macOS
def _list_cd_drives_macos() -> list[str]:
    # Run: diskutil list -plist
    # Parse with plistlib
    # For each disk in AllDisks: run diskutil info -plist
    # Filter where 'OpticalDiscType' is present
    # Return device paths like '/dev/disk4'
```

```python
# read_disc() on macOS
def _read_disc_macos(drive: str) -> DiscToc | None:
    # libdiscid accepts macOS device paths
    # Use the raw device for performance: /dev/rdisk4 not /dev/disk4
    raw_device = drive.replace("/dev/disk", "/dev/rdisk")
    return discid.read(raw_device, features=["mcn", "isrc"])
    # The DiscToc construction mirrors the Windows path
```

```python
# eject() on macOS
def _eject_macos(drive: str) -> None:
    # 'drutil eject' ejects the active optical drive
    # 'diskutil eject /dev/disk4' targets a specific device
    subprocess.run(["diskutil", "eject", drive], check=False)
```

**Windows-specific code remains untouched** behind `if sys.platform == "win32":` guards. Add parallel `elif sys.platform == "darwin":` branches.

### 5.2 Sub-track 2b — Bundled ffmpeg with libcdio for macOS ARM64 (3–5 days)

Standard macOS ffmpeg distributions (Homebrew, evermeet.cx) **do not** include libcdio support. The ripper's primary code path requires it. Three options were considered:

| Option | Effort | Code change | Recommended |
|---|---|---|---|
| **A. Build ffmpeg with libcdio in CI** | 2–4 days | None — existing libcdio code path works as-is | **Yes** |
| B. Add macOS raw CD reader via POSIX I/O | 1–2 days | Significant new code in `ripper.py` | No (entitlement complexity) |
| C. Bundle `cdparanoia` as a second binary | 2–3 days | New execution path in `ripper.py` | No (extra binary, extra maintenance) |

**Option A implementation:**

Add a new GitHub Actions job (or a step in the macOS build job) that:

1. Installs build dependencies via Homebrew: `autoconf automake libtool pkg-config nasm yasm`
2. Builds `libcdio` from source (current stable: 2.1.0):
   ```bash
   curl -L https://ftp.gnu.org/gnu/libcdio/libcdio-2.1.0.tar.bz2 | tar xj
   cd libcdio-2.1.0
   ./configure --prefix=$BUILD_PREFIX --enable-static --disable-shared
   make -j$(sysctl -n hw.ncpu) && make install
   ```
3. Builds `libcdio-paranoia` (needed for some ffmpeg integrations):
   ```bash
   curl -L https://ftp.gnu.org/gnu/libcdio/libcdio-paranoia-10.2+2.0.2.tar.bz2 | tar xj
   # similar configure/make/install
   ```
4. Builds `ffmpeg` from source with libcdio:
   ```bash
   curl -L https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz | tar xJ
   cd ffmpeg-7.1.1
   PKG_CONFIG_PATH=$BUILD_PREFIX/lib/pkgconfig ./configure \
     --prefix=$BUILD_PREFIX \
     --enable-libcdio \
     --enable-static \
     --disable-shared \
     --pkg-config-flags="--static" \
     --extra-ldflags="-L$BUILD_PREFIX/lib"
   make -j$(sysctl -n hw.ncpu)
   ```
5. Caches the resulting `ffmpeg` binary as a workflow artifact for the main build job to consume.

Verify the binary: `./ffmpeg -formats 2>&1 | grep libcdio` must show the demuxer.

**Zero code changes in `ripper.py`**: the existing libcdio code path at [ripper.py:254-275](lyon/core/ripper.py:254) is fully cross-platform — it just needs a libcdio-enabled binary.

### 5.3 Sub-track 2c — libdiscid bundling (1–2 days)

For packaged builds, `libdiscid.dylib` must be present in the bundle.

Two approaches:

1. **Build libdiscid from source in CI** (cleanest):
   ```bash
   curl -L https://ftp.musicbrainz.org/pub/musicbrainz/libdiscid/libdiscid-0.6.4.tar.gz | tar xz
   cd libdiscid-0.6.4
   ./configure --prefix=$BUILD_PREFIX
   make && make install
   ```
2. **Extract from Homebrew bottle** (faster but less reproducible).

Place the resulting `libdiscid.0.dylib` (and any version-numbered symlinks) into `bin/libdiscid.dylib` for the bundle.

**Loader path resolution on macOS:**

Unlike Windows (where `bin/` on `PATH` is sufficient), macOS uses `DYLD_LIBRARY_PATH` or `@rpath` linking. The existing `_ensure_bin_dir_on_path()` in [cd_detect.py:138](lyon/core/cd_detect.py:138) sets `PATH` but does not set `DYLD_LIBRARY_PATH`.

Three solutions, in order of cleanliness:

1. **PyInstaller rpath fix-ups (recommended)**: PyInstaller's macOS builds automatically rewrite library load paths to `@executable_path/...` for bundled `.dylib` files. Place `libdiscid.dylib` in the bundle's `Contents/Frameworks/` (PyInstaller does this automatically when a binary is listed in `binaries=` in the spec).
2. Set `DYLD_LIBRARY_PATH` before `discid` is imported. Slightly fragile; affected by macOS SIP restrictions.
3. Build libdiscid with `--install-name @rpath/libdiscid.0.dylib` and let the dynamic loader find it via the rpath.

Option 1 is the right answer; the existing PyInstaller spec already declares `binaries=` from `bin/`.

### 5.4 Sub-track 2d — Hardware validation (1–2 days)

- Acquire a USB optical drive. SuperDrive (Apple's discontinued unit) works fine; current alternatives include Verbatim, LG, and Pioneer USB DVD drives.
- Insert an audio CD on the dev Mac.
- Validate end-to-end pipeline:
  1. Drive shows up in Lyon's drive list
  2. TOC is read
  3. MusicBrainz lookup resolves the album
  4. Rip to FLAC completes successfully
  5. CTDB verification succeeds for a known accurate disc
  6. Eject works

### 5.5 Requirements file update

In [requirements.txt:5](requirements.txt:5):

```text
# Before
discid>=1.2; sys_platform == "win32"

# After
discid>=1.2; sys_platform == "win32" or sys_platform == "darwin"
```

In [diagnostics.py:88](lyon/core/diagnostics.py:88), `check_libdiscid()` needs to recognize macOS as a supported platform — change the warning branch to apply only to platforms other than win32 and darwin.

### Exit criterion
A real audio CD inserted into a USB optical drive on the dev Mac can be identified, ripped to FLAC, tagged with MusicBrainz metadata, CTDB-verified, and ejected — all from the source app.

---

## 6. Phase 3 — Build Pipeline & DMG Packaging (4–6 days)

**Objective:** CI produces a signed, notarized `.dmg` installer.

### 6.1 macOS PyInstaller spec

Create `build/lyon-macos.spec`. Key differences from the Windows spec:

```python
# Generate .icns from PNG (use Pillow + iconutil, or pillow-iconutil)
# Bundle ffmpeg, libdiscid.dylib, libvlc.dylib, libvlccore.dylib, plugins/

a = Analysis([str(ROOT / "main.py")], ...)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, ..., console=False, icon=icon_icns_path)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="LyonMusicManager")
app = BUNDLE(
    coll,
    name="Sea Lyon Media Manager.app",
    icon=icon_icns_path,
    bundle_identifier="com.sealyon.mediamanager",
    info_plist={
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© Sea Lyon",
        "CFBundleDocumentTypes": [],  # add file associations later if wanted
    },
)
```

### 6.2 Icon generation

Generate `.icns` from the existing brand PNG. Two approaches:

1. Use `iconutil` (Apple-provided, requires correctly sized PNGs in an `.iconset` folder):
   ```bash
   mkdir -p AppIcon.iconset
   sips -z 16 16   lyon-app-icon.png --out AppIcon.iconset/icon_16x16.png
   sips -z 32 32   lyon-app-icon.png --out AppIcon.iconset/icon_16x16@2x.png
   sips -z 32 32   lyon-app-icon.png --out AppIcon.iconset/icon_32x32.png
   sips -z 64 64   lyon-app-icon.png --out AppIcon.iconset/icon_32x32@2x.png
   sips -z 128 128 lyon-app-icon.png --out AppIcon.iconset/icon_128x128.png
   sips -z 256 256 lyon-app-icon.png --out AppIcon.iconset/icon_128x128@2x.png
   sips -z 256 256 lyon-app-icon.png --out AppIcon.iconset/icon_256x256.png
   sips -z 512 512 lyon-app-icon.png --out AppIcon.iconset/icon_256x256@2x.png
   sips -z 512 512 lyon-app-icon.png --out AppIcon.iconset/icon_512x512.png
   sips -z 1024 1024 lyon-app-icon.png --out AppIcon.iconset/icon_512x512@2x.png
   iconutil -c icns AppIcon.iconset
   ```
2. Use a Python library like `pillow-iconutil` to generate the `.icns` directly in the spec (mirrors how the Windows spec generates `.ico` from PNG).

Approach 2 is consistent with the existing Windows pattern.

### 6.3 VLC bundling

VLC for macOS is distributed as a `.dmg` containing `VLC.app`, which has the framework structure:

```
VLC.app/Contents/MacOS/
  lib/libvlc.dylib
  lib/libvlccore.dylib
  plugins/*.dylib  (large — ~200 MB worth)
```

For Sea Lyon's bundle, copy the minimum needed:

```
bin/vlc/
  libvlc.dylib
  libvlccore.dylib
  plugins/                  (full plugins directory)
```

This mirrors the existing Windows layout. The `_configure_vlc_runtime_path()` function in [playback_backend.py](lyon/core/playback_backend.py) already adds `bin/vlc/` to `PATH` and sets `VLC_PLUGIN_PATH` — works as-is on macOS.

**Important**: VLC plugins on macOS are heavy. If bundle size is a concern, prune unused plugin categories (gui, services_discovery, lua, etc.). The minimum for audio playback + EQ is typically:
- `plugins/access/` (file, etc.)
- `plugins/audio_output/` (auhal for CoreAudio)
- `plugins/audio_filter/` (equalizer)
- `plugins/codec/` (decoders)
- `plugins/demux/` (format support)

Pruning saves ~100 MB. Test thoroughly after pruning.

### 6.4 GitHub Actions workflow

New file: `.github/workflows/macos-build.yml`

```yaml
name: macOS build

on:
  workflow_dispatch:

jobs:
  build-ffmpeg:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - name: Cache ffmpeg artifact
        id: ffmpeg-cache
        uses: actions/cache@v4
        with:
          path: ffmpeg-bin
          key: macos-arm64-ffmpeg-libcdio-7.1.1
      - name: Build ffmpeg with libcdio
        if: steps.ffmpeg-cache.outputs.cache-hit != 'true'
        run: |
          # See Phase 2 sub-track 2b for the full build script
          ...

  build-libdiscid:
    runs-on: macos-14
    steps:
      - name: Build libdiscid
        run: |
          # Build from source as documented in Phase 2 sub-track 2c
          ...

  build-app:
    runs-on: macos-14
    needs: [build-ffmpeg, build-libdiscid]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Download bundled binaries from build jobs
        # Copy ffmpeg, libdiscid.dylib, VLC framework files into bin/
      - name: Install Python dependencies
        run: |
          python -m pip install -r requirements.txt pyinstaller
      - name: Build .app bundle
        run: python -m PyInstaller --noconfirm build/lyon-macos.spec
      - name: Sign and notarize
        # See Phase 4
      - name: Create DMG
        run: |
          npm install -g create-dmg
          create-dmg "dist/Sea Lyon Media Manager.app" dist/
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: LyonMusicManager-macos
          path: dist/*.dmg
```

### 6.5 DMG creation

Options:
1. `create-dmg` (npm package) — easy, customizable background image, drag-to-Applications shortcut
2. `hdiutil` (built into macOS) — more verbose; lower-level

`create-dmg` is the simpler choice for a polished installer.

### Exit criterion
CI on `macos-14` produces `LyonMusicManager-X.Y.Z.dmg`. Installing the DMG on a fresh macOS ARM64 machine produces a working `Sea Lyon Media Manager.app` in `/Applications/`.

---

## 7. Phase 4 — Code Signing & Notarization (3–5 days)

**Objective:** the app launches on a fresh Mac without Gatekeeper warnings.

### 7.1 Prerequisites

- Enroll in the Apple Developer Program ($99/year individual or $299/year organization). Approval can take 24–48 hours; in some regions it can take longer if Apple requires a D-U-N-S number.
- Generate a "Developer ID Application" certificate via Xcode or the Apple Developer portal.
- Export the certificate + private key as a `.p12` file.

### 7.2 GitHub Actions secrets

Store in repository secrets:
- `MACOS_CERTIFICATE_P12_BASE64` — base64-encoded `.p12` file
- `MACOS_CERTIFICATE_PASSWORD` — the `.p12` export password
- `MACOS_NOTARY_APPLE_ID` — Apple ID email
- `MACOS_NOTARY_TEAM_ID` — 10-character team identifier from the developer portal
- `MACOS_NOTARY_PASSWORD` — app-specific password generated at appleid.apple.com (not the Apple ID's actual password)

### 7.3 Signing step in CI

```bash
# Import the certificate into a temporary keychain
echo "$MACOS_CERTIFICATE_P12_BASE64" | base64 --decode > certificate.p12
security create-keychain -p "" build.keychain
security default-keychain -s build.keychain
security unlock-keychain -p "" build.keychain
security import certificate.p12 -k build.keychain -P "$MACOS_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "" build.keychain

# Sign every binary inside the app bundle (deep signing)
codesign --force --deep --options=runtime --timestamp \
  --sign "Developer ID Application: <Your Name> (<TEAM_ID>)" \
  "dist/Sea Lyon Media Manager.app"

# Verify
codesign --verify --deep --strict --verbose=2 "dist/Sea Lyon Media Manager.app"
```

**`--options=runtime`** enables the hardened runtime, required by notarization.

### 7.4 Notarization

```bash
# Zip the .app for submission
ditto -c -k --keepParent "dist/Sea Lyon Media Manager.app" SeaLyon.zip

# Submit to Apple, wait for result
xcrun notarytool submit SeaLyon.zip \
  --apple-id "$MACOS_NOTARY_APPLE_ID" \
  --team-id "$MACOS_NOTARY_TEAM_ID" \
  --password "$MACOS_NOTARY_PASSWORD" \
  --wait

# Staple the notarization ticket onto the .app
xcrun stapler staple "dist/Sea Lyon Media Manager.app"

# Build the DMG from the stapled .app, then sign the DMG too
create-dmg "dist/Sea Lyon Media Manager.app" dist/
codesign --force --timestamp --sign "Developer ID Application: ..." dist/*.dmg
```

### 7.5 Verification

On a fresh Mac (or one where the certificate is not in the system trust cache):
- Mount the DMG
- Drag to `/Applications/`
- Launch — should open without any Gatekeeper warning
- If a warning appears, run `spctl -a -vv "/Applications/Sea Lyon Media Manager.app"` to diagnose

### Exit criterion
The DMG from CI installs and runs on a clean macOS ARM64 system without any Gatekeeper intervention. `spctl -a -vv` reports `accepted` and `source=Notarized Developer ID`.

---

## 8. Phase 5 — Hardening & Release (3–5 days)

### 8.1 macOS-native UI polish

PySide6 automatically maps menu items to the standard macOS menu bar when given the right roles:

- `QAction("About", ...).setMenuRole(QAction.AboutRole)`
- `QAction("Settings", ...).setMenuRole(QAction.PreferencesRole)`

These already work in [main_window.py](lyon/ui/main_window.py:245) by name convention — verify that "About" and "Open Settings" land in the application menu rather than the Help and Settings menus when running on macOS.

### 8.2 File associations (optional)

Add `CFBundleDocumentTypes` entries to the `info_plist` in the PyInstaller spec to register Sea Lyon as an opener for `.flac`, `.mp3`, etc. Each association needs a UTI declaration. Optional — defer unless requested.

### 8.3 Documentation

- Update [README.md](README.md) with macOS install instructions (mount DMG → drag to Applications).
- Update [docs/BUILD.md](docs/BUILD.md) with the local macOS build procedure.
- New file `docs/macos-distribution.md`: notarization process, secrets management, certificate renewal calendar (Developer ID certs expire after 5 years).

### 8.4 Production testing matrix

Smoke-test the final DMG on multiple OS versions:

| macOS version | Hardware | Status |
|---|---|---|
| 11.0 Big Sur | M1 | First Apple Silicon — confirm minimum target works |
| 12.x Monterey | M1/M2 | |
| 13.x Ventura | M1/M2 | |
| 14.x Sonoma | M1/M2/M3 | |
| 15.x Sequoia | M1/M2/M3 | Check new permission prompts |
| 26.x (current) | M1+ | Dev environment |

You will not have all these versions natively — rely on CI macOS runners and a small set of test machines. As an alternative, MacStadium and AWS EC2 Mac instances provide on-demand macOS hosts.

### 8.5 Auto-update (deferred)

Frameworks like Sparkle integrate with macOS for in-app updates. Significant additional work; defer to a later release.

### Exit criterion
The signed DMG passes the smoke-test on at least two macOS versions (the minimum supported and the current). README and BUILD docs reflect the new installation flow.

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Building ffmpeg with libcdio for ARM64 fails on first attempt | Medium | Medium | Phase 0 spike must produce a working build before Phase 2 begins |
| libcdio-paranoia transitive dependency build issues | Medium | Medium | Static-link everything; test the produced binary with `-formats` and a real disc |
| macOS Sequoia (15)+ adds new permission prompts for USB media | Medium | Low | These are first-time consents; document the expected UX |
| Notarization rejected for an obscure reason | Low | High | Submit a test build early in Phase 4; Apple's `notarytool log` output is specific |
| VLC plugin pruning breaks an edge case | Medium | Low | Default to bundling all plugins; only prune after release if size pressure exists |
| Apple Developer Program account approval delayed | Low | Medium | Apply at start of Phase 0; can take 1–2 weeks |
| Developer ID certificate expires mid-cycle | Low | High | Calendar the 5-year expiration in `docs/macos-distribution.md` |
| `discid` Python package has a macOS-specific bug | Low | Medium | The library is mature and ARM64-tested; report upstream if blocked |
| PySide6 has an ARM64-specific UI quirk | Low | Low | Issue tracker has historical Apple Silicon reports; fixable case-by-case |

---

## 10. Open Questions

1. **Apple Developer enrollment**: who is the legal entity? Individual ($99/year) or organization ($299/year + D-U-N-S number)? Affects approval time.
2. **Distribution channel**: direct DMG download only, or also Mac App Store? The App Store has much stricter sandboxing rules that would break CD ripping and may break libVLC bundling. Recommend direct DMG only.
3. **VLC plugin bundle size**: full bundle (~250 MB) vs pruned (~150 MB)? Pruned is faster to download but more brittle. Start with full bundle; revisit later.
4. **Auto-update**: implement Sparkle now or defer? Recommend defer unless this is a paid product.
5. **CI runner cost**: macOS GitHub Actions runners are 10× more expensive than Linux runners. Estimate ~20 minutes per build × frequency to budget.

---

## 11. Effort Summary

| Phase | Estimate | Critical-path? |
|---|---|---|
| Phase 0 — Spike & Decisions | 2–3 days | Yes — validates the ffmpeg-libcdio build |
| Phase 1 — Source-run cleanup | 3–5 days | Yes |
| Phase 2 — CD ripping (2a/2b/2c/2d) | 8–12 days | Yes — largest scope |
| Phase 3 — Build pipeline & DMG | 4–6 days | Yes |
| Phase 4 — Signing & notarization | 3–5 days | No (can begin in parallel with Phase 3 once .app builds) |
| Phase 5 — Hardening & release | 3–5 days | No |
| **Total** | **23–36 working days (~5–7 weeks)** | |

**Ongoing maintenance:** ~10–15% per release for the dual-platform CI cost and macOS spot-check. Certificate renewal every 5 years. macOS major version compatibility checks once per year (typically September after Apple's annual release).

---

## 12. Hardware Requirements

To complete this plan you need:
- One Apple Silicon Mac for development (M1 or later)
- One USB optical drive for CD ripping validation (any USB external CD/DVD drive will work)
- Test Macs for production smoke-testing on multiple macOS versions, OR access to MacStadium / AWS EC2 Mac instances
- Apple Developer Program enrollment

---

## 13. Recommended Decision

This plan represents a strictly higher-ROI investment than the Windows 8.1 port. Apple Silicon is the entire current Mac lineup; the addressable market expands materially. The code base is already partially macOS-aware, the technical risks are well-understood, and the unknowns (ffmpeg-libcdio build, notarization) are bounded by Phase 0 and Phase 4 respectively.

Proceed with Phase 0 as the go/no-go gate. If the spike succeeds in 3 days, commit to the full plan.
