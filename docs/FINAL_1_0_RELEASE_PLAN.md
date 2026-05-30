# Sea Lyon 1.0 Final Release Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` if this plan is implemented task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Sea Lyon Media Manager 1.0.0 as a public, installable release with working Windows x64 and macOS Apple Silicon artifacts, accurate release notes, verified update metadata, and a repeatable smoke-test checklist.

**Architecture:** Keep the current PySide6/PyInstaller application and GitHub Actions release flow. Windows remains the primary supported package; macOS Apple Silicon ships in the same 1.0 release only after its workflow and manual smoke pass. The in-app updater remains a notification-and-download flow, not an in-place patcher.

**Tech Stack:** Python 3.14, PySide6, PyInstaller, Inno Setup 6, create-dmg, GitHub Actions, pytest, Ruff, Sparkle-style appcast XML.

---

## Release Decision

Ship target: **1.0.0 public release**.

Supported installer targets:

- Windows 10 / 11, 64-bit: `SeaLyonMediaManager-1.0.0-Setup.exe` and `SeaLyonMediaManager-1.0.0-windows.zip`.
- macOS 11+, Apple Silicon: `SeaLyonMediaManager-1.0.0-arm64.dmg`.

Fallback rule:

- If macOS CI or macOS smoke testing fails after the release branch is otherwise ready, publish Windows 1.0.0 and move macOS to a clearly labeled post-1.0 milestone. Do not leave README, appcast, or GitHub Release text claiming macOS support unless the DMG is actually shipped and smoke-tested.

## Review Snapshot

Review date: 2026-05-29.

Commands run:

```sh
.venv/bin/python -m pytest -q
```

Result:

```text
822 passed, 2 skipped in 61.08s
```

Additional checks:

```sh
.venv/bin/python scripts/changelog-section.py 1.0.0
.venv/bin/python scripts/changelog-section.py 0.9.0-rc2
.venv/bin/python -m ruff --version
```

Results:

```text
error: no section found for 1.0.0
error: no section found for 0.9.0-rc2
No module named ruff
```

Code paths reviewed:

- `lyon/core/updater.py`: appcast parsing, platform enclosure selection, version comparison, HTTP failure handling.
- `lyon/ui/main_window.py`: startup update scheduling, worker lifecycle, manual update check, skipped-version behavior.
- `scripts/generate-appcast.py`: release-note extraction, multi-OS appcast generation, historical item preservation.
- `.github/workflows/windows-build.yml`: pytest gate, artifact production, changelog extraction, draft release creation.
- `.github/workflows/macos-build.yml`: arm64 build, vendor binary staging, signing/notarization gates, multi-OS appcast upload.
- `build/lyon.iss`: installer versioning, registry keys, uninstall behavior, legal file packaging.

## Release Blockers

| ID | Severity | Finding | Evidence | Required fix |
| --- | --- | --- | --- | --- |
| R1 | Blocker | Version and changelog are out of sync, so tag builds will fail release-note extraction. | `lyon/__init__.py` is `0.9.0-rc2`; `CHANGELOG.md` has `0.9.0-rc1` but no `0.9.0-rc2` or `1.0.0`; `scripts/changelog-section.py 1.0.0` fails. | Add a final `## [1.0.0] - 2026-06-04` changelog section before tagging, then bump `lyon/__init__.py`, README, and release docs to `1.0.0`. |
| R2 | Blocker | Platform story conflicts across docs. | README advertises Windows and macOS packages; `docs/BUILD.md` says only Windows is packaged; changelog says the RC is Windows-only while macOS CI exists. | Pick and document the 1.0 support surface. Recommended: Windows x64 plus macOS arm64 if both workflows and smoke tests pass. |
| R3 | High | Changelog claims release docs exist, but they are missing. | `CHANGELOG.md` references `docs/RELEASING.md` and `docs/RELEASE_CHECKLIST.md`; neither exists in `docs/`. | Create both docs or remove the claims. The release checklist is required for 1.0 smoke testing. |
| R4 | High | Ruff is configured but not installable or enforced in CI. | `pyproject.toml` defines Ruff rules; `requirements-build.in` omits Ruff; `.venv/bin/python -m ruff --version` fails. | Add Ruff to build requirements, regenerate lockfiles, and run `python -m ruff check lyon tests scripts` in both release workflows before packaging. |
| R5 | Medium | Inno Setup manual fallback version is stale. | `build/lyon.iss` defaults `AppVersion` to `0.8.0` if `/DAppVersion` is omitted. | Change the fallback to fail loudly or keep it synchronized with `lyon/__init__.py` during the 1.0 bump. |
| R6 | Medium | Known-issues text is stale. | `CHANGELOG.md` says dependency hashes are not pinned, but `requirements.txt` is now generated with hashes; it also says appcast publishing is manual while `publish-appcast.yml` exists. | Rewrite known issues for 1.0: unsigned Windows installer, ffmpeg GPL notice, macOS unsigned fallback if secrets are absent, any true remaining limitations. |

## Non-Blocking Observations

- The full pytest suite is healthy and substantially above the CI floor of 680 tests.
- The updater implementation correctly avoids cross-platform installer downloads when appcast enclosures are tagged with `sparkle:os`.
- The Windows workflow verifies VLC and fpcalc packaging before installer creation.
- The macOS workflow already waits for the Windows installer asset before generating the final multi-OS appcast.
- Legal files exist (`EULA.txt`, `PRIVACY.md`, `THIRD_PARTY_NOTICES.txt`), but they need one final review against the actual bundled ffmpeg/VLC/libdiscid/fpcalc artifacts.

## Implementation Schedule

Assumption: work starts Friday, 2026-05-29. Dates can slide, but task order should not.

### Day 1 - Friday, 2026-05-29 - Release branch and blocker cleanup

- [ ] Create a release branch from the clean current branch:

```sh
git switch -c release/1.0.0
```

- [ ] Resolve the platform decision in writing:
  - Windows x64 is mandatory for 1.0.
  - macOS arm64 is included only if the macOS workflow and physical smoke test pass.

- [ ] Update release metadata:
  - Change `lyon/__init__.py` to `__version__ = "1.0.0"` only when the final release notes are ready.
  - Update README current version from `0.9.0-rc1` to `1.0.0`.
  - Update any RC-only wording that conflicts with the chosen support surface.

- [ ] Rewrite `CHANGELOG.md`:
  - Move real 1.0 changes under `## [1.0.0] - 2026-06-04`.
  - Keep `## [Unreleased]` empty for post-1.0 work.
  - Remove false claims about missing hashes and manual appcast publishing.
  - Keep true known issues: unsigned Windows installer, SmartScreen warning, ffmpeg GPL notice, and macOS unsigned fallback if signing secrets are absent.

- [ ] Create `docs/RELEASING.md` with the exact tag, CI, smoke-test, publish, and appcast verification procedure.

- [ ] Create `docs/RELEASE_CHECKLIST.md` with checkboxes for:
  - Windows 10 clean install.
  - Windows 11 clean install.
  - Windows upgrade install over the latest RC.
  - macOS Apple Silicon install.
  - First run, library scan, audio playback, video playback, radio, podcasts, YouTube acknowledgement/download flow, CD detection/rip path, DLNA/cast, diagnostics bundle, update check, uninstall data-retention prompt, HiDPI checks.

### Day 2 - Monday, 2026-06-01 - CI hardening and release workflow validation

- [ ] Add Ruff to `requirements-build.in`:

```text
ruff==<current-compatible-version>
```

- [ ] Regenerate `requirements-build.txt` with hashes using the repo's existing uv compile workflow.

- [ ] Add a Ruff gate after dependency install and before pytest in both workflows:

```sh
python -m ruff check lyon tests scripts
```

- [ ] Harden `build/lyon.iss` so manual builds cannot silently produce `0.8.0` installers.

- [ ] Verify changelog extraction:

```sh
.venv/bin/python scripts/changelog-section.py 1.0.0
```

Expected:

```text
## [1.0.0] - 2026-06-04
```

- [ ] Verify local tests:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

Expected: all tests pass, with the collected count still above the workflow floor.

- [ ] Verify local Ruff:

```sh
.venv/bin/python -m ruff check lyon tests scripts
```

Expected: no errors.

### Day 3 - Tuesday, 2026-06-02 - Artifact dry run

- [ ] Trigger `workflow_dispatch` for `.github/workflows/windows-build.yml`.

- [ ] Trigger `workflow_dispatch` for `.github/workflows/macos-build.yml`.

- [ ] Confirm both workflows:
  - Install hashed dependencies.
  - Run Ruff.
  - Collect and run pytest.
  - Fetch verified vendor binaries.
  - Build artifacts.
  - Upload artifacts with version `1.0.0`.

- [ ] Download artifacts from both workflow runs.

- [ ] Verify SHA-256 manifests:

```pwsh
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-Setup.exe
Get-FileHash -Algorithm SHA256 SeaLyonMediaManager-1.0.0-windows.zip
```

```sh
shasum -a 256 SeaLyonMediaManager-1.0.0-arm64.dmg
```

- [ ] Generate a temporary appcast locally with placeholder artifact URLs and confirm the XML contains both Windows and macOS enclosures when macOS ships.

### Day 4 - Wednesday, 2026-06-03 - Manual smoke testing

- [ ] Run the full `docs/RELEASE_CHECKLIST.md` on Windows 10.

- [ ] Run the full `docs/RELEASE_CHECKLIST.md` on Windows 11.

- [ ] Run macOS Apple Silicon smoke if macOS remains in scope.

- [ ] For each platform, capture:
  - OS version.
  - Installer filename and SHA-256.
  - App version shown in About/System Info.
  - Runtime Diagnostics result.
  - Any crash logs or user-visible warnings.

- [ ] Fix only release-blocking issues:
  - App will not launch.
  - Installer fails.
  - Bundled VLC/ffmpeg/fpcalc/libdiscid missing.
  - Update check points to wrong platform or wrong version.
  - Data-loss issue.
  - Legal or release-note inaccuracy.

### Day 5 - Thursday, 2026-06-04 - Final tag and draft release

- [ ] Ensure the release branch is clean:

```sh
git status --short
```

- [ ] Run final local gates:

```sh
.venv/bin/python scripts/changelog-section.py 1.0.0
.venv/bin/python -m ruff check lyon tests scripts
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

- [ ] Merge the release branch.

- [ ] Create the final tag:

```sh
git tag -a v1.0.0 -m "Sea Lyon Media Manager 1.0.0"
git push origin v1.0.0
```

- [ ] Wait for Windows and macOS tag workflows.

- [ ] Confirm draft GitHub Release contains:
  - Windows installer.
  - Windows portable zip.
  - Windows SHA256SUMS.
  - macOS DMG, if in scope.
  - macOS SHA256SUMS, if in scope.
  - `appcast.xml`.
  - Release body from `CHANGELOG.md`.

- [ ] Download the draft release assets and repeat SHA verification before publishing.

### Day 6 - Friday, 2026-06-05 - Publish and monitor

- [ ] Publish the GitHub Release.

- [ ] Confirm `.github/workflows/publish-appcast.yml` deploys Pages successfully.

- [ ] Verify public appcast:

```sh
curl -fsSL https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml
```

Expected:

- Contains `sparkle:version` `1.0.0`.
- Contains the Windows installer URL.
- Contains the macOS DMG URL only if macOS shipped.
- Preserves prior appcast entries if any existed.

- [ ] Install the last RC, run **Help -> Check for Updates...**, and confirm it offers 1.0.0.

- [ ] Install 1.0.0 fresh and confirm **Help -> Check for Updates...** reports the latest version.

- [ ] Post release links:
  - README download section.
  - GitHub Release notes.
  - SmartScreen notes.
  - Privacy policy page.

- [ ] Monitor for 48 hours:
  - GitHub Issues.
  - Appcast availability.
  - Installer download and checksum reports.
  - macOS notarization/Gatekeeper reports, if macOS shipped.

## Definition of Done

- `lyon/__init__.py`, README, changelog, installer filenames, GitHub Release title, and appcast all agree on `1.0.0`.
- Full pytest suite passes locally and in both release workflows.
- Ruff runs locally and in both release workflows.
- Release artifacts are produced by CI, not manually assembled.
- SHA-256 manifests match downloaded artifacts.
- `docs/RELEASING.md` and `docs/RELEASE_CHECKLIST.md` exist and match the actual 1.0 flow.
- Manual smoke testing is completed for every platform advertised publicly.
- Appcast is deployed after publishing and returns the correct platform installer in the app.
- Stale RC-only wording is removed from public docs.

## Post-1.0 Backlog

- Authenticode signing for Windows.
- Strict-LGPL ffmpeg distribution option.
- Fully automated macOS appcast coordination if the dual-workflow timing proves fragile.
- Broader static analysis beyond the current conservative Ruff rules.
- In-place updater support, if desired, after the download-only updater has been proven in production.
