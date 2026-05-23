# Releasing Sea Lyon Media Manager

This is the step-by-step procedure for shipping a public release. The
v1.0 release strategy targets Windows 10 / 11 (64-bit) only; macOS and
Linux are source-only. The full plan and decision log live in
[`IMPLEMENTATION_PLAN_1.0.md`](../IMPLEMENTATION_PLAN_1.0.md).

A "release" is anything tagged `vMAJOR.MINOR.PATCH` (optionally with a
pre-release suffix like `-rc1`). Pushing the tag triggers the CI
pipeline at [`.github/workflows/windows-build.yml`](../.github/workflows/windows-build.yml).

## TL;DR

1. Update [`CHANGELOG.md`](../CHANGELOG.md) — move work out of
   "Unreleased" into a new `## [X.Y.Z] — YYYY-MM-DD` section.
2. Bump `__version__` in [`lyon/__init__.py`](../lyon/__init__.py).
3. Commit on `LMM-MASTER`: `git commit -am "Release vX.Y.Z"`.
4. Tag and push: `git tag vX.Y.Z && git push --tags`.
5. Wait for CI to produce a draft GitHub Release.
6. **Smoke-test** the installer on a clean Windows VM (use the
   [release checklist](RELEASE_CHECKLIST.md) when it lands in Week 4).
7. If green: publish the draft Release. If red: delete the tag, fix,
   re-tag.
8. Commit the regenerated `appcast.xml` to the `gh-pages` branch (1.0
   is manual; automation lands in 1.1).

## Pre-flight (do this once)

- A GitHub Personal Access Token with `repo` scope is **not** required
  for tag pushes — the workflow uses `GITHUB_TOKEN` automatically.
- `gh-pages` branch should exist with at minimum:
  ```
  /appcast.xml      <-- the in-app updater reads this
  /PRIVACY.md       <-- linked from the app
  ```
  If `gh-pages` doesn't exist yet, create it with the contents of the
  first release's `dist/appcast.xml` artifact.

## 1. Update the CHANGELOG

Open `CHANGELOG.md` and:

- Move every bullet under `## [Unreleased]` into a new section:
  ```markdown
  ## [1.0.0] — 2026-XX-XX

  ### Added
  - ...
  ### Changed
  - ...
  ### Fixed
  - ...
  ```
- Leave `## [Unreleased]` empty at the top.

The release workflow extracts this section verbatim and uses it as the
GitHub Release body, so it should read well as a public announcement.

## 2. Bump the version

Edit [`lyon/__init__.py`](../lyon/__init__.py):

```python
__version__ = "1.0.0"
```

This is read by:

- The installer (CI uses it as `OutputBaseFilename`).
- The PyInstaller bundle metadata.
- The in-app updater (compared against the appcast feed).
- The About dialog.
- The Help → Check for Updates flow.

## 3. Commit + tag

```cmd
git checkout LMM-MASTER
git merge LMM-DEV
git commit -am "Release v1.0.0"
git tag v1.0.0
git push origin LMM-MASTER --tags
```

## 4. Wait for CI

The push triggers `.github/workflows/windows-build.yml`. The job:

1. Installs Python deps.
2. Runs the full pytest suite. Aborts on any failure **or** if the
   collected-test count drops below `PYTEST_FLOOR`.
3. Downloads ffmpeg / libdiscid / VLC / fpcalc with SHA-256 verification.
4. Smoke-tests imports, the VLC backend, and fpcalc.
5. Builds the PyInstaller bundle.
6. Compiles `build/lyon.iss` with Inno Setup, producing:
   - `dist/SeaLyonMediaManager-{ver}-Setup.exe`
   - `dist/SeaLyonMediaManager-{ver}-windows.zip`
   - `dist/SeaLyonMediaManager-{ver}-SHA256SUMS.txt`
7. Extracts the matching CHANGELOG section and writes
   `release-notes.md`.
8. Generates `dist/appcast.xml` from CHANGELOG + the freshly-uploaded
   installer URL.
9. Creates a **draft** GitHub Release with the installer, zip,
   SHA256SUMS, and `appcast.xml` attached.

Watch the run at
<https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/actions>.

## 5. Smoke-test the artifact

Download the draft Release's installer to a **clean Windows VM** (or
a fresh user without `%APPDATA%\LyonMusicManager\`). Walk through
the release checklist in `docs/RELEASE_CHECKLIST.md` (lands in Week
4). At minimum:

- [ ] Installer runs end-to-end (SmartScreen → "More info → Run anyway").
- [ ] EULA + third-party notices pages render.
- [ ] App launches; first-run wizard completes.
- [ ] Audio playback works.
- [ ] CD detection + rip works on a real machine.
- [ ] DLNA cast to a real renderer works.
- [ ] YouTube acknowledgement gate appears once, then disappears.
- [ ] EQ audibly affects output.
- [ ] Uninstaller asks about `%APPDATA%` and removes only when asked.

## 6. Publish (or roll back)

**If green**, hit "Publish release" on the draft Release page.

**If red**, do not publish. Instead:

```cmd
git tag -d v1.0.0
git push origin :refs/tags/v1.0.0
```

Fix the issue, re-tag, push again. Avoid amending or force-pushing
the release tag once it's been public.

## 7. Update the appcast on gh-pages

For v1.0 this step is manual; automate in 1.1.

```cmd
git fetch origin gh-pages
git worktree add ../sealyon-ghpages gh-pages
copy dist\appcast.xml ..\sealyon-ghpages\appcast.xml
cd ..\sealyon-ghpages
git commit -am "Appcast: v1.0.0"
git push origin gh-pages
cd ..\Sea-Lyon-Media-Manager
git worktree remove ../sealyon-ghpages
```

Verify the feed is reachable:

```
curl -I https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml
```

A `200 OK` with `Content-Type: application/xml` (or `text/xml`)
means existing installs will pick it up on the next periodic check.

## 8. Announce

- Write a short post linking the release page + CHANGELOG.
- If you set up a public Discord / Reddit / mailing list, post the
  installer URL + SmartScreen note.

## Pre-releases (rc / beta tags)

Tags like `v0.9.0-rc1` follow the same flow. Recommended for 1.0:

```cmd
git tag v0.9.0-rc1 && git push --tags
```

This validates the entire pipeline end-to-end one week before the
real 1.0 tag.

## Hot-fix releases

For patch-level fixes (1.0.1, 1.0.2, …):

1. Cherry-pick the fix onto `LMM-MASTER`.
2. Update CHANGELOG with a `## [1.0.1]` section.
3. Bump `__version__`.
4. Tag and push. The rest of the pipeline is identical.

## Verifying downloaded artefacts

```pwsh
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-Setup.exe
```

Compare against the value in
`SeaLyonMediaManager-1.0.0-SHA256SUMS.txt`. The two SHA-256 lines (one
per file) ship alongside the installer; readers should not trust an
unsigned installer without checking the hash.

## Reverting a release

```cmd
gh release delete v1.0.0 --yes
git tag -d v1.0.0
git push origin :refs/tags/v1.0.0
```

Revert the version bump in `lyon/__init__.py`, restore the CHANGELOG
section back into `## [Unreleased]`, and push the revert commit. Then
re-cut a fresh release with a new tag (`v1.0.1`); do not re-use a
yanked tag.

## See also

- [`docs/BUILD.md`](BUILD.md) — full local + CI build guide.
- [`IMPLEMENTATION_PLAN_1.0.md`](../IMPLEMENTATION_PLAN_1.0.md) —
  v1.0 plan, decisions, calendar, and risks.
- [`CHANGELOG.md`](../CHANGELOG.md) — release history.
