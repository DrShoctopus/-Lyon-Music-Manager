# Release Code Review Report

Review date: 2026-05-25
Repository: Sea Lyon Media Manager
Review mode: release-readiness review updated after critical, high, medium, and low fix passes

## Executive Summary

Sea Lyon Media Manager is now substantially closer to a stable 1.0 release. The previously identified critical appcast publication blocker has been fixed, the high-priority credential/dependency/native-binary/documentation issues have been addressed, and the actionable medium-priority correctness issues now have code fixes and regression coverage.

The remaining release gate is target-platform certification: the built Windows installer still needs final smoke testing on Windows 10 and Windows 11, including native media binaries, CD hardware, DLNA/network behavior, and updater behavior against release artifacts.

Current verification:

- `PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider` -> `711 passed in 55.37s`
- Focused release-readiness tests -> `80 passed in 17.96s`
- `.venv/bin/python -m py_compile lyon/core/updater.py lyon/core/settings.py lyon/ui/main_window.py` -> passed
- GitHub workflow YAML parse for `.github/workflows/windows-build.yml` and `.github/workflows/publish-appcast.yml` -> passed
- `pyproject.toml` TOML parse -> passed
- `git diff --check` -> clean
- `.venv/bin/python -m pip check` -> `No broken requirements found`

PDF generation note: `pandoc` and `wkhtmltopdf` are not installed. This PDF was generated with the repository-local PySide6 Markdown-to-PDF renderer in `scripts/_md_to_pdf.py`.

## Overall Release Readiness

Recommendation: Conditionally ready after Windows release certification.

| Area | Status | Notes |
| --- | --- | --- |
| Core functionality | Mostly ready | Automated suite passes with 711 tests. |
| Packaging | Conditionally ready | Draft appcast publication is fixed; Windows artifact smoke testing still required. |
| Updater | Improved | rc-to-final comparison and failed-check backoff are covered by tests. |
| Dependencies | Improved | Runtime/build lockfiles are hash-pinned; vulnerability scanning remains a recommended gate. |
| Security posture | Improved | Last.fm secret is no longer embedded into packaged builds; diagnostics redact user credentials. |
| Documentation | Improved | Release/build docs and manual QA checklist were refreshed. |
| Test strategy | Good baseline | Remaining gaps are hardware/packaged-app/manual QA items. |

## Critical Blockers

No open critical blockers remain in the repository.

### CR-1: Appcast was deployed before draft release approval

- Severity: Critical
- Status: Fixed
- File path: `.github/workflows/windows-build.yml`, `.github/workflows/publish-appcast.yml`
- Verification: workflow YAML parse passed; full test suite passed

The tag build no longer deploys `appcast.xml` to GitHub Pages while the release is still a draft. It now attaches the generated appcast to the draft release, and `.github/workflows/publish-appcast.yml` publishes the appcast only after the GitHub Release is public.

## High Priority Issues

No open in-repository high-priority issues remain.

### H-1: Last.fm API secret was embedded into packaged desktop binaries

- Severity: High
- Status: Fixed
- File path: `.github/workflows/windows-build.yml`, `lyon/core/scrobbler.py`, `lyon/core/settings.py`, `lyon/ui/settings_dialog.py`, `lyon/core/diagnostics.py`

The workflow no longer writes Last.fm credentials into source before packaging. Users can enter their own Last.fm API key/shared secret in settings, the scrobbler signs requests from those settings, and diagnostics redact the key and secret.

### H-2: Release dependency locking was incomplete

- Severity: High
- Status: Fixed
- File path: `requirements.txt`, `requirements-build.txt`, `requirements-build.in`, `requirements.in`

Runtime and build dependency locks are now generated with hashes. Build dependencies including PyInstaller, Pillow, and pytest are pinned through `requirements-build.in` and the generated lockfile.

### H-3: Local Windows build resolved latest fpcalc dynamically

- Severity: High
- Status: Fixed
- File path: `scripts/build-windows.ps1`, `scripts/README.md`

The local Windows build now uses a pinned Chromaprint/fpcalc version instead of querying GitHub's latest release endpoint.

### H-4: Public version and release documentation was stale

- Severity: High
- Status: Fixed
- File path: `README.md`, `docs/BUILD.md`, `docs/RELEASING.md`, `scripts/README.md`

The public docs now reflect the current release workflow, dependency-locking process, appcast publication path, version status, and test-suite size.

### H-5: 1.0 release cannot be fully certified from this environment alone

- Severity: High
- Status: Open external release gate
- File path: `docs/RELEASE_CHECKLIST.md`, `docs/RELEASING.md`

This is not an in-repository code defect. Stable 1.0 still requires Windows artifact validation on release builds. Required evidence should include Windows 10 and Windows 11 smoke-test results, installer checksum, app version, logs, native binary checks, and pass/fail notes.

## Medium Priority Issues

No open medium-priority code issues remain from this review.

### M-1: Drag-and-drop could report unsupported files as successfully added

- Severity: Medium
- Status: Fixed
- File path: `lyon/ui/main_window.py`, `tests/test_main_window_integration.py`

`MainWindow.dropEvent` now uses `SUPPORTED_EXTS`, indexes files through `index_file`, and reports added, updated, unchanged, skipped, and failed counts accurately.

### M-2: Updater version comparison ignored pre-release semantics

- Severity: Medium
- Status: Fixed
- File path: `lyon/core/updater.py`, `tests/test_updater.py`

The updater now sorts pre-release versions before their matching final versions. Regression tests cover `1.0.0-rc1` to `1.0.0` and `rc1` to `rc2`.

### M-3: Appcast generation in CI did not preserve previously published items

- Severity: Medium
- Status: Fixed
- File path: `.github/workflows/windows-build.yml`, `tests/test_release_workflows.py`

The release workflow fetches the current Pages-hosted `appcast.xml` into `dist/appcast.xml` before regenerating the appcast, allowing `scripts/generate-appcast.py` to preserve existing items when available.

### M-4: DLNA server sharing scope needed clearer disclosure

- Severity: Medium
- Status: Improved; manual validation still required
- File path: `lyon/ui/main_window.py`, `docs/RELEASE_CHECKLIST.md`

The app already required confirmation before enabling DLNA and settings already exposed the bind address. The success toast now includes the advertised server URL, and the release checklist requires testers to record bind address/adaptor exposure across VPN, guest, and virtual network cases.

### M-5: Update failures could retry on every startup

- Severity: Medium
- Status: Fixed
- File path: `lyon/core/settings.py`, `lyon/ui/main_window.py`, `tests/test_main_window_integration.py`

Automatic update failures now record `last_update_failure_ts` and back off for four hours. Manual update checks still run immediately and surface the failure on demand.

## Low Priority Issues

No open low-priority cleanup item requires pre-1.0 code changes.

### L-1: Build and release docs contained stale future-tense guidance

- Severity: Low
- Status: Fixed
- File path: `docs/BUILD.md`, `docs/RELEASING.md`

The docs now describe the current draft release flow, appcast history fetch, post-publication appcast deployment, and release-hardening checks.

### L-2: Historical review/planning documents could confuse 1.0 status

- Severity: Low
- Status: No action needed
- File path: repository root

The historical files named in the original review (`FEATURE_AND_CODE_REVIEW.md`, `IMPLEMENTATION_PLAN_1.0.md`, `REVIEW_NEXT_STEPS.md`) are no longer present in the repository.

### L-3: No repository-level lint or type-check gate was visible

- Severity: Low
- Status: Improved
- File path: `pyproject.toml`

A conservative Ruff configuration now exists for syntax/import-oriented release hardening. Ruff itself is not installed in the current virtual environment, so the config was parsed but `ruff check` was not run.

### L-4: Some modules are large enough to slow maintenance

- Severity: Low
- Status: Deferred intentionally
- File path: `lyon/ui/library_view.py`, `lyon/ui/main_window.py`, `lyon/ui/knowledge_base_dialog.py`, `lyon/ui/video_player_view.py`, `lyon/core/library.py`, `lyon/core/metadata.py`, `lyon/core/dlna_server.py`, `lyon/core/ripper.py`

Large-module refactoring remains a post-1.0 maintainability task. It should not be bundled into the release-hardening patch unless a specific bug requires it.

## Bugs and Functional Risks

| Severity | Finding | Status | Evidence |
| --- | --- | --- | --- |
| Critical | Appcast published before release approval | Fixed | Separate `publish-appcast` workflow publishes only after release publication. |
| High | Embedded Last.fm secret | Fixed | Workflow secret-writing removed; settings-based credentials and redaction added. |
| High | Non-reproducible dependency graph | Fixed | Hash-pinned runtime/build locks generated. |
| High | Local build downloads latest fpcalc | Fixed | Local script uses pinned Chromaprint/fpcalc version. |
| Medium | Drag/drop false success | Fixed | Import result counts and regression test added. |
| Medium | Pre-release update comparison | Fixed | rc-to-final tests added. |
| Medium | DLNA broad local-network access | Improved | UI disclosure/checklist improved; manual adapter validation remains. |
| Medium | Update failure retry behavior | Fixed | Failure timestamp and backoff tests added. |

Remaining functional risks are primarily release-environment risks: Windows installer behavior, native binary discovery, real CD hardware, real DLNA devices/adapters, and end-to-end update behavior from packaged builds.

## Stale / Dead / Orphaned Code

| Item | Classification | Current status |
| --- | --- | --- |
| Historical review/planning docs | No action needed | Previously named files are absent from the repository. |
| Dynamic latest-fpcalc path | Removed/replaced | Local Windows build no longer resolves latest Chromaprint release. |
| Draft appcast deployment path | Removed/replaced | Draft workflow no longer deploys Pages appcast. |
| Old release documentation text | Updated | Build/release docs now describe the current workflow. |

No tracked `.DS_Store`, `.pytest_cache`, or `__pycache__` files were found during the original review.

## Code Quality Findings

The codebase is cleaner for release after the fix passes:

- User-facing import feedback now reflects real library indexing results.
- Updater retry state is explicit in settings rather than inferred from success timestamps only.
- Appcast publication is separated from release build/approval.
- Dependency and native-binary versions are more reproducible.
- A conservative lint configuration now gives maintainers a place to add release-hardening checks.

Maintainability recommendations after 1.0:

- Split large UI/core modules by responsibility.
- Add a CI check for generated lockfile freshness.
- Install and run Ruff in CI once the team agrees on the initial rule set.
- Keep release metadata, test floor, native binary versions, and appcast URL in a single release checklist or source of truth.

## Testing Gaps

Current automated coverage is strong for the fixed issues:

- Drag/drop skipped-file behavior is covered.
- Updater pre-release ordering is covered.
- Failed automatic update backoff is covered.
- Appcast history fetch ordering in the workflow is covered.
- Last.fm credentials and diagnostics redaction are covered.

Remaining gaps before 1.0:

| Area | Gap | Required validation |
| --- | --- | --- |
| Packaged app | Unit tests do not prove packaged VLC/ffmpeg/fpcalc/libdiscid behavior. | Installer smoke tests on Windows 10 and 11. |
| CD ripping | Hardware and drive behavior cannot be fully covered in CI. | Manual rip and verification using real hardware. |
| DLNA | Adapter exposure depends on local network topology. | Manual LAN/VPN/guest-network validation. |
| Updater | End-to-end install/update behavior requires release artifacts. | Private test appcast against packaged builds. |
| Dependency security | No vulnerability scanner was available locally. | Run `pip-audit`, Safety, Dependabot, or equivalent in CI/release checklist. |
| Lint gate | Config exists, but Ruff is not installed in the current venv. | Add Ruff to dev/build tooling or CI before enforcing. |

## Dependency and Security Findings

Dependency posture has improved:

- Runtime and build lockfiles are hash-pinned.
- Build tooling is pinned.
- `pip check` passes.

Remaining dependency/security release gates:

- Run a dependency vulnerability scan and record results.
- Verify lockfile regeneration instructions in CI or release docs.
- Confirm no credentials are committed or generated into packaged binaries.
- Confirm diagnostics continue to redact Last.fm and ListenBrainz credentials.
- Validate DLNA network exposure on real Windows network configurations.

## Platform-Specific Risks

### Windows packaging

The remaining 1.0 risks are target-platform risks:

- Installer runs and uninstalls cleanly.
- Installed app starts from Start Menu/desktop shortcut.
- VLC/libVLC playback works from the installed layout.
- ffmpeg-based ripping/downloading works.
- fpcalc fingerprinting works.
- libdiscid/CD features work with real hardware.
- SmartScreen expectations and checksum verification match docs.

### Update distribution

The appcast publication ordering issue is fixed in repository configuration. The remaining release validation is to publish a private/test appcast and confirm packaged builds detect, skip, and open updates correctly.

### Multi-adapter networks

DLNA sharing should be tested with Wi-Fi, Ethernet, VPN, guest/private networks, and local virtual adapters. Testers should record the advertised URL and bind address.

## Manual QA Checklist

Use this checklist against final 1.0 release candidate artifacts, not a development checkout.

### Install, launch, and first run

- Install on a clean Windows 10 machine.
- Install on a clean Windows 11 machine.
- Launch from Start Menu and desktop shortcut.
- Confirm version matches installer, README, release notes, and GitHub tag.
- Complete first-run setup.
- Confirm diagnostic logs are created.

### Library and file management

- Add a single supported audio file.
- Add a folder containing supported and unsupported files.
- Drag/drop supported files.
- Drag/drop unsupported or unreadable files and verify skipped/error messaging.
- Scan a large nested library.
- Remove a library path.
- Move or rename a scanned file and verify recovery/re-indexing.

### Playback

- Play MP3, FLAC, AAC/M4A, OGG/Opus, WAV, and WMA where supported.
- Play supported video formats.
- Verify play, pause, seek, next, previous, shuffle, repeat, and queue behavior.
- Verify volume, mute, equalizer, ReplayGain, and output-device behavior.
- Verify behavior when the playing file is deleted or moved.

### Metadata and enrichment

- Edit common metadata fields.
- Save metadata and reopen the app.
- Test cover art lookup/local cover behavior.
- Test lyrics display if enabled.
- Test fpcalc/AcoustID behavior.
- Verify network-unavailable behavior.

### CD ripping

- Detect an inserted audio CD.
- Read disc metadata.
- Rip to each supported output mode.
- Verify progress, cancellation, and error messages.
- Verify AccurateRip/CTDB or equivalent verification paths.

### Podcasts, radio, and online media

- Add valid and invalid podcast feeds.
- Play/download a podcast episode.
- Add and play radio streams.
- Test YouTube acknowledgement, search, download, and failure handling.
- Confirm network timeouts show useful errors.

### DLNA

- Enable DLNA and confirm the local-network warning.
- Record success-toast URL and bind address.
- Browse from a trusted LAN client.
- Try VPN/guest/virtual adapters if available.
- Disable DLNA and confirm the server stops.
- Restart and confirm setting persistence.

### Updater

- Configure a private test appcast for an older packaged build.
- Confirm update detection.
- Confirm download URL opens correctly.
- Confirm no update is shown for equal/newer installed versions.
- Confirm rc-to-final behavior.
- Confirm failed automatic checks back off while manual checks still run.

### Installer, upgrade, and uninstall

- Upgrade from the previous public version.
- Verify settings and library survive upgrade.
- Verify native binaries are replaced correctly.
- Uninstall and confirm app files are removed.
- Confirm user data retention/deletion behavior matches documentation.
- Reinstall after uninstall.

## Recommended Fix Order

Completed:

1. Separate appcast deployment from draft release creation.
2. Remove packaged Last.fm secret injection.
3. Lock runtime and build dependencies.
4. Pin local Windows fpcalc resolution.
5. Update release/build docs.
6. Fix drag/drop import feedback.
7. Fix updater pre-release comparison.
8. Preserve appcast history during CI generation.
9. Clarify DLNA exposure in UI/docs.
10. Add updater failure backoff.
11. Add conservative lint configuration.

Remaining:

1. Run Windows 10 and Windows 11 release artifact smoke tests.
2. Run dependency vulnerability scanning.
3. Run real CD hardware validation.
4. Run real DLNA adapter/device validation.
5. Run packaged-app updater validation against a private test appcast.

## 1.0 Release Gate Checklist

### Required gates

- [x] Appcast publication is separated from draft release creation.
- [x] Draft release appcast is not deployed before the GitHub Release is public.
- [x] Last.fm packaged credential strategy is resolved.
- [x] Runtime dependency lockfile is generated and used.
- [x] Build dependency lockfile is generated and used.
- [x] Local and CI Windows builds use pinned native binary versions.
- [x] README, docs, installer metadata, package version, and release notes are aligned for the current candidate.
- [x] Full automated test suite passes.
- [x] Test count exceeds the configured workflow floor.
- [x] `pip check` passes.
- [x] Release artifacts include SHA256 checksum generation in the workflow.
- [ ] Dependency vulnerability scan is run and reviewed.
- [ ] Windows installer smoke test passes on Windows 10.
- [ ] Windows installer smoke test passes on Windows 11.
- [ ] Upgrade from previous public version passes.
- [ ] Updater test appcast path passes.
- [ ] DLNA sharing behavior is manually verified.
- [ ] CD ripping is manually verified on real hardware.
- [ ] Release notes include known limitations and upgrade notes.

### Optional but recommended gates

- [x] Add conservative lint/import configuration.
- [x] Add rc-to-final updater tests.
- [x] Add drag/drop partial-success tests.
- [x] Add workflow assertion preventing appcast-history regression.
- [ ] Install/run Ruff in CI.
- [ ] Split large modules after 1.0.

## Final Recommendation

Sea Lyon Media Manager is conditionally ready for a 1.0 release candidate after the repository fixes in this review. It should not be published as stable 1.0 until Windows release artifact certification is complete.

The minimum remaining bar is:

1. Windows 10 and Windows 11 installer smoke tests pass.
2. Native VLC, ffmpeg, fpcalc, and libdiscid behavior works from the installed layout.
3. CD ripping is verified on real hardware.
4. DLNA behavior is verified across representative network adapters.
5. Packaged updater behavior is verified against a test appcast.
6. Dependency vulnerability scan results are reviewed and accepted.
