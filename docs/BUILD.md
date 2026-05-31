# Building Sea Lyon Media Manager

**1.0 release platforms:** Windows 10 and 11 (64-bit) is mandatory.
macOS Apple Silicon is included only if the CI-built DMG and physical
smoke test on the oldest advertised macOS version pass before
publishing. Linux remains source-only and best-effort.

**Toolchain:** Python 3.14, PyInstaller, Inno Setup 6 for Windows,
create-dmg and optional Apple Developer ID signing/notarization for
macOS.

There are four ways to build:

1. **CI** — trigger `workflow_dispatch` for the Windows and macOS
   workflows, or push a `v*.*.*` tag. GitHub Actions produces release
   artifacts and SHA-256 manifests. This is the canonical path.
2. **Local Windows end-to-end** — run `scripts\build-windows.ps1` from the
   project root on a Windows machine with Python 3.14 and Inno Setup 6
   installed. Produces the same artifacts as CI.
3. **Local macOS helpers** — use the macOS scripts under `scripts/` to
   stage vendor binaries, build the `.app`, and create a DMG while
   debugging the CI flow.
4. **Manual** — for incremental debugging only (no installer); covered
   under §4 below.

## 1. Prerequisites

- **Python 3.14** from python.org.
  - Windows: 64-bit CPython; tick "Add Python to PATH".
  - macOS: arm64-native CPython, not Rosetta.
- **Inno Setup 6** from <https://jrsoftware.org/isinfo.php> for the
  Windows installer step.
- **Xcode command line tools** and Homebrew are used by the macOS
  workflow helpers. The workflow installs `create-dmg` when building
  the DMG.

Binary runtimes (ffmpeg, libdiscid, fpcalc, VLC) are fetched
automatically by the build scripts / workflows with SHA-256 verification.
For source runs you can drop pre-fetched copies into `bin/` to skip the
download.

For pre-populated source runs, place the files into `bin/` at the
project root:

```
bin\
  ffmpeg.exe
  discid.dll
  fpcalc.exe
  vlc\
    libvlc.dll
    libvlccore.dll
    plugins\
```

## 2. Install dependencies

```cmd
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-build.txt
```

## 3. Run from source

```cmd
py main.py
```

This expects either a populated `bin\` directory or system-installed
ffmpeg / VLC / libdiscid on PATH. Open **Help → Runtime Diagnostics**
to see which dependencies are wired.

## 4. Build a stand-alone bundle (no installer)

```cmd
pyinstaller build\lyon.spec
```

The packaged app appears under `dist\LyonMusicManager\`. Double-click
`LyonMusicManager.exe` or zip the folder for distribution.

For the installer step, continue to §5.

## 5. Build the installer locally (recommended)

```cmd
scripts\build-windows.ps1
```

This script:

1. Creates / refreshes `.venv` and installs `requirements-build.txt`.
2. Downloads ffmpeg, libdiscid, fpcalc, and VLC into `bin\` with
   SHA-256 verification against the upstream `.sha256` sidecar or the
   project's `SHA256SUMS` files.
3. Runs PyInstaller via `build\lyon.spec`.
4. Zips the bundle to
   `dist\SeaLyonMediaManager-{version}-windows.zip`.
5. Compiles `build\lyon.iss` with Inno Setup, producing
   `dist\SeaLyonMediaManager-{version}-Setup.exe`.

Flags:

- `-SkipBinaries` — assume `bin\` is already populated; skip downloads.
- `-SkipZip` — keep the PyInstaller bundle but don't zip it.
- `-SkipInstaller` — don't run Inno Setup (e.g. if it's not installed).
- `-Clean` — wipe `.venv`, `dist\`, and generated PyInstaller artefacts
  before starting.

## 6. CI workflows

### Windows

`.github/workflows/windows-build.yml` is the Windows release flow, hosted on
`windows-latest`. Triggers:

- `workflow_dispatch` — manual; useful for verifying CI before tagging.
- `push: tags: ['v*.*.*']` — auto-creates a draft GitHub Release with
  the installer, portable zip, SHA-256 manifest, and `appcast.xml`
  attached.

The CI pipeline:

1. Installs Python deps from `requirements-build.txt`.
2. **Runs `pytest`** (must pass and collect at least `PYTEST_FLOOR`
   tests — currently 680). The build aborts if any test fails or the
   collected count drops, to catch silently-skipped tests.
3. Hash-verifies and downloads ffmpeg, libdiscid, VLC, and fpcalc.
   fpcalc is pinned to a known Chromaprint version
   (`CHROMAPRINT_VERSION` env var); do not auto-resolve "latest" from
   the GitHub API or builds become non-reproducible.
4. Smoke-tests imports + VLC backend + fpcalc.
5. Runs PyInstaller.
6. Reads `__version__` from `lyon/__init__.py` and uses it for output
   filenames.
7. Zips the bundle, installs Inno Setup, compiles `build\lyon.iss`,
   and computes a SHA-256 manifest.
8. Uploads the installer, zip, and SHA256SUMS as a single artifact.
9. On tag builds, fetches the current Pages-hosted `appcast.xml` into
   `dist\appcast.xml` before regenerating the feed so older release
   items are preserved when possible.
10. Attaches release artifacts and `appcast.xml` to a draft GitHub
   Release. The appcast is published by
   `.github/workflows/publish-appcast.yml` only after the Release is
   published.

The repository includes a conservative Ruff configuration in
`pyproject.toml` for release-hardening checks. It intentionally focuses
on syntax/import hazards first; broader formatting or typing rules should
be tightened after the 1.0 release branch is stable.

### macOS Apple Silicon

`.github/workflows/macos-build.yml` is the conditional macOS release
flow, hosted on an arm64 `macos-14` runner. Triggers:

- `workflow_dispatch` — manual; required for the 1.0 artifact dry run.
- `push: tags: ['v*.*.*']` — attaches the DMG and macOS SHA-256
  manifest to the draft GitHub Release.

The macOS pipeline:

1. Confirms the host and Python are arm64-native.
2. Installs Python deps from `requirements-build.txt`.
3. Runs the pytest collection floor and full suite.
4. Fetches arm64 ffmpeg, fpcalc, VLC, and libdiscid.
5. Builds the `.icns` icon and PyInstaller `.app`.
6. Injects libVLC, plugins, ffmpeg, fpcalc, and libdiscid into the app
   bundle.
7. Signs, notarizes, and staples when Apple Developer ID secrets are
   configured; otherwise emits an unsigned DMG.
8. Builds `SeaLyonMediaManager-{version}-arm64.dmg` and
   `SeaLyonMediaManager-{version}-macos-SHA256SUMS.txt`.
9. On tag builds, waits for the Windows installer asset before
   generating a multi-OS `appcast.xml`.

Do not advertise macOS support in README, release notes, or appcast
metadata unless the CI-built DMG passes the manual smoke checklist on
Apple Silicon.

## 7. Inno Setup details

`build\lyon.iss` is configured for:

- **Per-user or per-machine install** chosen at install time
  (`PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=dialog`).
- **License page** shows `EULA.txt`; user must accept before install.
- **Third-party notices page** shows `THIRD_PARTY_NOTICES.txt` before
  install (LGPL/GPL attribution; ffmpeg essentials is GPL-tainted).
- **Uninstaller prompt**: after the standard uninstall, the user is
  asked whether to also delete `%APPDATA%\LyonMusicManager\`
  (library, settings, cache, logs). Default is No.
- **Registry**: writes `HKCU\Software\Sea Lyon\Media Manager` with
  `InstalledVersion`, `InstallPath`, `AppcastUrl` so the in-app
  updater can find the release feed. All values are removed on
  uninstall.
- **Branding**: `WizardImageFile` is `docs\brand\lyon-splash.png`;
  small wizard image is `docs\brand\lyon-app-icon.png`.

## 8. VLC playback backend packaging

Sea Lyon prefers libVLC for local music playback so the 10-band
equalizer can drive VLC's real `AudioEqualizer`. Source installs need
both the Python binding from `requirements.txt` and a VLC runtime
discoverable by python-vlc.

For Windows packaging, the build pipeline downloads VLC 3.0.23 and
keeps only `libvlc.dll`, `libvlccore.dll`, and `plugins\` under
`bin\vlc\`. The app prepends that folder to PATH and sets
`VLC_PLUGIN_PATH` at runtime before importing python-vlc.

A system-wide 64-bit VLC install can still work for source runs, but
packaged releases always include `bin\vlc\` to avoid depending on the
target machine. If python-vlc or libVLC can't be created, the app
still launches but local audio, video, and audible EQ are disabled
until VLC is fixed.

## Troubleshooting

Open **Help → Runtime Diagnostics** to check whether ffmpeg,
libdiscid/discid, VLC/libVLC, fpcalc, and DLNA network access are
all available.

For support requests, use **Help → Copy Diagnostics to Clipboard** to
generate a redacted text bundle (versions, dependency check, log tail,
sanitised settings) that you can paste into an issue.

Common issues:

- **"ffmpeg not found"** — check that `bin\ffmpeg.exe` exists, or
  install ffmpeg system-wide and add to PATH.
- **CD not detected** — confirm `bin\discid.dll` exists. The app uses
  Windows API `GetDriveType` to find optical drives, so virtual drives
  may not show up.
- **Metadata never resolves** — check internet access, CTDB
  availability, and the MusicBrainz contact value in *Settings*.
  Hammering MusicBrainz with a generic User-Agent gets the IP
  rate-limited.
- **SmartScreen warning at install** — expected for v1.0 because the
  installer is unsigned. Click "More info → Run anyway". A code-signed
  build is planned for v1.1.

## 9. Verifying a release artefact

Every CI build emits `SeaLyonMediaManager-{version}-SHA256SUMS.txt`
alongside the installer and zip. To verify:

```pwsh
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-Setup.exe
```

and compare against the value in `SHA256SUMS.txt`.

## 10. Reproducing a build

To get byte-identical artefacts on two machines, you need:

1. The same Python 3.14.x point release.
2. The locked transitive dependency lists. Before tagging a release,
   regenerate `requirements.txt` and `requirements-build.txt` with `uv`
   from the `.in` files:
   ```pwsh
   pip install uv
   uv pip compile requirements.in --universal --python-version 3.14 --generate-hashes --output-file requirements.txt
   uv pip compile requirements-build.in --universal --python-version 3.14 --generate-hashes --output-file requirements-build.txt
   ```
3. The pinned binary runtimes from `windows-build.yml`'s `env:` block
   and `scripts/build-windows.ps1`.

PyInstaller is mostly deterministic but timestamps and a few caches
may differ; the SHA-256 of the unzipped `LyonMusicManager.exe` is
typically stable across runs of the same machine but not guaranteed
across different machines.
