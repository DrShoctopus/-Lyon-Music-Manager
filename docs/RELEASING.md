# Sea Lyon 1.0 Release Procedure

This procedure is the source of truth for publishing Sea Lyon Media
Manager 1.0.0. Windows x64 is mandatory. macOS Apple Silicon is included
only after the CI-built DMG and physical smoke test on the oldest
advertised macOS version pass.

## 1. Prepare The Branch

1. Work from a clean release branch based on the latest development
   branch.
2. Confirm release identity:

   ```sh
   .venv/bin/python -c "from lyon import __version__; assert __version__ == '1.0.0'"
   .venv/bin/python scripts/changelog-section.py 1.0.0
   ```

3. Confirm public docs agree on support:
   - Windows 10 / 11 x64 ships in 1.0.
   - macOS Apple Silicon ships only if the macOS gate passes on the
     oldest advertised macOS version.
   - Linux is source-only and best-effort.

4. Review legal and support files:
   - `EULA.txt`
   - `PRIVACY.md`
   - `THIRD_PARTY_NOTICES.txt`
   - `docs/SMARTSCREEN_NOTES.md`

## 2. Local Gates

Run these before tagging:

```sh
.venv/bin/python scripts/changelog-section.py 1.0.0
.venv/bin/python -m ruff check lyon tests scripts
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --collect-only -q
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Do not tag if any local gate fails.

Before triggering the release workflows, also dry-run appcast generation
with temporary output and placeholder artifact URLs:

```sh
.venv/bin/python scripts/generate-appcast.py \
  --version 1.0.0 \
  --installer-url https://example.invalid/SeaLyonMediaManager-1.0.0-Setup.exe \
  --installer-size 1 \
  --macos-installer-url https://example.invalid/SeaLyonMediaManager-1.0.0-arm64.dmg \
  --macos-installer-size 1 \
  --macos-minimum-system-version 11.0 \
  --release-url https://example.invalid/releases/tag/v1.0.0 \
  --output /tmp/sea-lyon-appcast.xml \
  --no-existing
```

Remove the macOS placeholder arguments if macOS has already been deferred
for the 1.0 release.

## 3. Artifact Dry Run

Trigger both workflows manually from GitHub Actions:

```sh
gh workflow run windows-build.yml --ref <release-branch>
gh workflow run macos-build.yml --ref <release-branch>
```

Confirm the Windows workflow:

- Installs `requirements-build.txt`.
- Runs the pytest collection floor and full test suite.
- Fetches ffmpeg, libdiscid, VLC, and fpcalc.
- Builds `SeaLyonMediaManager-1.0.0-Setup.exe`.
- Builds `SeaLyonMediaManager-1.0.0-windows.zip`.
- Uploads `SeaLyonMediaManager-1.0.0-SHA256SUMS.txt`.

Confirm the macOS workflow:

- Runs on arm64 hardware with arm64 Python.
- Installs `requirements-build.txt`.
- Runs the pytest collection floor and full test suite.
- Fetches arm64 ffmpeg, fpcalc, VLC, and libdiscid.
- Builds `SeaLyonMediaManager-1.0.0-arm64.dmg`.
- Uploads `SeaLyonMediaManager-1.0.0-macos-SHA256SUMS.txt`.
- Signs and notarizes if Apple Developer ID secrets are configured, or
  clearly produces an unsigned artifact.

If the macOS workflow, smoke test, or oldest-advertised-OS gate fails,
remove or narrow macOS claims in the README, release notes, appcast, and
GitHub Release body before publishing Windows 1.0.0.

If macOS ships but the physical smoke pass covers a newer support floor
than macOS 11.0, update `MACOS_MINIMUM_SYSTEM_VERSION` in
`.github/workflows/macos-build.yml` and the public release wording before
tagging.

## 4. Manual Smoke Tests

Download the CI artifacts and complete `docs/RELEASE_CHECKLIST.md` on:

- Windows 10 clean install.
- Windows 10 portable zip.
- Windows 11 clean install.
- Windows 11 portable zip.
- Windows upgrade install over the latest RC.
- macOS Apple Silicon, only if macOS remains in scope.

For each platform, record:

- OS version.
- Artifact filename.
- SHA-256.
- App version shown in About/System Info.
- Runtime Diagnostics result.
- Crashes, warnings, or missing bundled dependencies.

Fix only release blockers at this point:

- App will not launch.
- Installer or DMG cannot install.
- Bundled VLC, ffmpeg, fpcalc, or libdiscid is missing.
- Update check offers the wrong version or platform.
- Data-loss issue.
- Legal, privacy, release-note, or support-surface inaccuracy.

## 5. Tag And Draft Release

After local gates and smoke tests pass:

```sh
git status --short
git tag -a v1.0.0 -m "Sea Lyon Media Manager 1.0.0"
git push origin v1.0.0
```

Wait for the tag-triggered Windows and macOS workflows.

The draft GitHub Release must contain:

- `SeaLyonMediaManager-1.0.0-Setup.exe`
- `SeaLyonMediaManager-1.0.0-windows.zip`
- `SeaLyonMediaManager-1.0.0-SHA256SUMS.txt`
- `SeaLyonMediaManager-1.0.0-arm64.dmg`, only if macOS shipped
- `SeaLyonMediaManager-1.0.0-macos-SHA256SUMS.txt`, only if macOS shipped
- `appcast.xml`
- Release body extracted from `CHANGELOG.md`

Download the draft assets and verify hashes before publishing.

Windows:

```pwsh
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-Setup.exe
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-windows.zip
```

macOS:

```sh
shasum -a 256 SeaLyonMediaManager-1.0.0-arm64.dmg
```

## 6. Publish And Verify Appcast

Publish the GitHub Release only after smoke testing and hash checks.
Publishing triggers `.github/workflows/publish-appcast.yml`.

Verify Pages appcast:

```sh
curl -fsSL https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml
```

Expected:

- Contains `sparkle:version` `1.0.0`.
- Contains the Windows installer enclosure.
- Contains the macOS DMG enclosure only if macOS shipped.
- Preserves prior appcast entries if any existed.

Then verify updater behavior:

1. Install the last RC.
2. Run **Help -> Check for Updates...**.
3. Confirm it offers `1.0.0`.
4. Install `1.0.0`.
5. Run **Help -> Check for Updates...**.
6. Confirm it reports the latest version.

## 7. Monitor

For 48 hours after publish, monitor:

- GitHub Issues.
- Appcast availability.
- Installer download and checksum reports.
- SmartScreen reports.
- macOS notarization or Gatekeeper reports, if macOS shipped.
