# Sea Lyon Media Manager — v1.0 Release Implementation Plan

**Working dir:** `/Users/shoctopus/Documents/Sea Lyon Media Manager`
**Branch:** `LMM-DEV` (target merge: `LMM-MASTER`)
**Current version:** `0.8.0` → target `1.0.0`
**Target ship window:** ~4 weeks of dev work
**Source of truth for blockers:** `FEATURE_AND_CODE_REVIEW.md`, sections 1.1–1.3 + overlapping Appendix B quick wins.

---

## Decisions Log (locked-in before work starts)

| # | Decision | Choice |
|---|---|---|
| 1 | Platform scope | **Windows-only.** macOS/Linux remain source-only; strip from advertised surface. |
| 2 | Code signing | **Deferred to 1.1.** Ship 1.0 unsigned; mitigate with SmartScreen FAQ + first-run toast. Budget OV cert (~$300–700/yr) for 1.1. |
| 3 | Crash reporting | **Local-only.** `RotatingFileHandler` + Help → Open Log Folder / Copy Diagnostics. No telemetry, no Sentry. |
| 4 | Auto-update | **GitHub Pages appcast** at `https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml`. In-app updater polls; "Download" opens the installer URL in the browser. No in-place patching. |
| 5 | EULA | **MIT + 3-paragraph user-responsibility tail** covering CD ripping legality, YouTube ToS, DLNA broadcasting, scrobbler privacy. |
| 6 | ffmpeg license | **Ship gyan.dev essentials as-is for 1.0.** Reproduce GPL-2 text in `THIRD_PARTY_NOTICES.txt`. Accept bundle is effectively GPL. Plan strict-LGPL ffmpeg swap for 1.1. |
| 7 | MusicBrainz contact | `https://github.com/DrShoctopus/Sea-Lyon-Media-Manager` |
| 8 | YouTube acknowledgement | **Lazy** — first YouTube tab open or first download-dialog open. Not gated in first-run wizard. |
| 9 | Uninstall + delete %APPDATA% | **Reset everything.** First-run wizard + YouTube ack fire again on reinstall. |
| 10 | Release candidate strategy | **Cut `v0.9.0-rc1` at end of Week 3** to dry-run the tag-triggered CI pipeline before `v1.0.0`. |

---

## Section 1 — Audit Findings (Current State vs. Required)

### 1.1 Installer & bundling

**`build/lyon.iss`** — *Exists.* Inno Setup 6 script that:
- Sets `AppId` (stable GUID — good).
- `PrivilegesRequired=lowest` with elevation prompt allowed (good — per-user install possible).
- Output: `dist\SeaLyonMediaManager-{AppVersion}-Setup.exe`.
- `CloseApplications=yes` and `MinVersion=10.0` (good).
- Desktop-icon optional task; no auto-start option.

**Gaps in `lyon.iss`:**
1. No license page — needs `[Setup] LicenseFile=..\EULA.txt`.
2. No third-party notices page — needs `InfoBeforeFile` for `THIRD_PARTY_NOTICES.txt`.
3. No uninstaller `%APPDATA%\LyonMusicManager\` cleanup — currently leaves user data forever after uninstall.
4. No `[Code]` section for a "delete user data?" prompt.
5. No `[Registry]` writes for the in-app updater (appcast URL, installed version).
6. No branded wizard images.

**`build/lyon.spec`** — *Exists, correct.* Bundles `bin/`, brand assets, excludes most Qt sub-modules. Hidden imports for `discid`, `vlc`, `yt_dlp`, `acoustid`. No changes needed unless we add new bundled files.

**`.github/workflows/windows-build.yml`** — *Exists; partially complete.*
- Triggered only by `workflow_dispatch` — not tag-triggered.
- Downloads ffmpeg, libdiscid, fpcalc, VLC into `bin/` (good).
- Caches binary runtimes by version key (good).
- **Does NOT run Inno Setup (`ISCC`)** — only zips `dist\LyonMusicManager\*`.
- **Does NOT pin downloads by hash** (the PowerShell build script does, but the workflow doesn't). Mirror compromise → silently bad build.
- **Does NOT run pytest before packaging.**
- **Does NOT compute a SHA-256 of the output.**
- **fpcalc version is resolved from "latest"** — non-reproducible.

VLC/ffmpeg: `scripts/build-windows.ps1` downloads both, verifies SHA-256 (good). The GitHub Actions workflow also downloads them but does **not** verify hashes.

### 1.2 Legal, license, attribution

**`lyon/ui/about.py`** — *Stub only.* Two string constants only.
**`MainWindow.show_about()`** (line ~1453) — wires those into a `QMessageBox`. No license text, no clickable "open license folder", no clear bundled-version reporting.

**LGPL compliance gap (legal-critical):**
- VLC = LGPL-2.1+ → must reproduce LGPL text.
- Qt/PySide6 = LGPL-3 (with Qt LGPL exception) → must reproduce both.
- ffmpeg essentials = LGPL-2.1+ but **includes GPL components** (libx264, libx265). Bundle is effectively GPL.
- libdiscid, Chromaprint/fpcalc = LGPL-2.1.
- Mutagen = GPL-2+ — additional GPL dep.
- musicbrainzngs = GPL-2+.
- yt-dlp = Unlicense.
- defusedxml, requests, certifi, watchdog, urllib3 = Apache/MIT/PSF (permissive).

**MusicBrainz contact** — `lyon/core/settings.py` line ~226: `musicbrainz_contact: str = "https://example.invalid/lyon"`. **Placeholder leaks into every outbound MB/CTDB request today.**

**YouTube disclaimer** — `lyon/ui/first_run_dialog.py` exists but has **no YouTube acknowledgement**. No `youtube_acknowledged` flag on `Settings`.

**EULA / PRIVACY / CHANGELOG / THIRD_PARTY_NOTICES** — none exist on disk. `LICENSE` (MIT) is present at repo root; that's the only legal artifact today.

### 1.3 Crash & diagnostics

**`lyon/app.py`** (42 lines) — does **no** logging setup. No `RotatingFileHandler`, no `basicConfig`, no log file. Module-level `logging.getLogger(__name__)` calls are effectively dropped at runtime.

**Help menu** (`lyon/ui/main_window.py`) — currently: Knowledge Base (F1), Library Statistics, Runtime Diagnostics, About. **No "Open Log Folder" or "Copy Diagnostics" actions.**

`metadata-diagnostics.log` likely exists (emitted by `lyon/core/metadata.py`); main-app log does not.

### 1.4 Network / HTTP hygiene

**User-Agent headers:**
- `lyon/core/metadata.py` — `musicbrainzngs.set_useragent(...)` (good) + `_user_agent()` helper for CTDB/CAA (good). **Reads contact from settings** — placeholder leaks unless changed.
- `lyon/core/podcast.py:21` — `PODCAST_USER_AGENT = "Sea Lyon Media Manager/Podcast"`. **No version, no contact URL.** Needs cleanup.
- `lyon/core/radio.py` — no outbound HTTP (parsing only).
- `lyon/core/scrobbler.py` — uses default `requests.Session()` UA. Needs explicit UA.
- `lyon/core/yt_downloader.py` — yt-dlp manages own UA. Out of scope.

**Timeouts:** All audited modules (`metadata.py`, `podcast.py`, `scrobbler.py`) have explicit timeouts. ✅

**Defused XML:** `podcast.py` uses `defusedxml.ElementTree` ✅. Spot-audit other XML paths during Week 1 buffer.

### 1.5 Release engineering

- `requirements.txt` pins direct deps but **not transitive deps** (`urllib3`, `certifi`, etc.). Not byte-reproducible.
- No semver tags beyond `0.2.0`. No `CHANGELOG.md`.
- `README.md` mentions macOS/Linux in 5 places (lines 15, 71, 212, 230, 275) — must be stripped per scoping decision.

### 1.6 Auto-update

No auto-update code in the tree. Greenfield.

### 1.7 What already works (no need to touch)

- PyInstaller spec ✅
- Build script with hash-pinned downloads (PowerShell only) ✅
- Inno Setup script (needs polish, not redo) ✅
- Diagnostics infrastructure ✅
- First-run dialog (needs YouTube panel) ✅
- 637-test pytest suite ✅
- HTTP timeouts ✅
- defusedxml ✅
- libVLC + ffmpeg + fpcalc bundling in CI ✅

---

## Section 2 — Work Tracks

### Track A — Installer & Bundling

**Goal:** A double-clickable `SeaLyonMediaManager-1.0.0-Setup.exe` that installs everything users need with no DLL prerequisites, and a clean uninstaller.

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| A1 | `build/lyon.iss` | Add `[Setup] LicenseFile=..\EULA.txt`, `InfoBeforeFile=..\THIRD_PARTY_NOTICES.txt`, `InfoAfterFile=..\RELEASE_NOTES.txt` (or wire from CHANGELOG). | 1 h | C1, C2, E1 | Installer shows EULA + accept gate. Third-party notices visible before install. Release notes shown after install. |
| A2 | `build/lyon.iss` | Add `[Code]` section with `CurUninstallStepChanged` handler offering Yes/No `MsgBox` "Also remove your library, settings, and cache from %APPDATA%\LyonMusicManager?". If yes, `DelTree` `%APPDATA%\LyonMusicManager\`. | 3 h | — | Uninstaller prompts; removes only if user agrees. Fresh-install after uninstall + delete yields a true first-run. |
| A3 | `build/lyon.iss` | Add `[Registry]` entry under `HKCU\Software\Sea Lyon\Media Manager` with `InstalledVersion`, `InstallPath`, `AppcastUrl` for the in-app updater + crash reporter to read. | 1 h | B1 | Registry key present after install; removed on uninstall. |
| A4 | `.github/workflows/windows-build.yml` | Add `Install Inno Setup` step (chocolatey `choco install innosetup -y`), then `ISCC.exe build\lyon.iss /DAppVersion=$env:APP_VERSION` after PyInstaller. Upload `.exe` as artifact. | 3 h | A1 | CI run produces `SeaLyonMediaManager-{ver}-Setup.exe` as downloadable artifact. |
| A5 | `.github/workflows/windows-build.yml` | Hash-pin every download (ffmpeg, libdiscid, VLC, fpcalc) via `build/manifest.json` (or workflow `env:` block). Verify SHA-256 before extracting. Match logic already in `scripts/build-windows.ps1`. | 4 h | — | Tampered mirror fails build. Hash check logged in CI. |
| A6 | `.github/workflows/windows-build.yml` | Pin Chromaprint/fpcalc to a known version (e.g. `1.5.1`); drop "latest" REST call. | 1 h | A5 | Two consecutive CI runs use identical fpcalc. |
| A7 | `.github/workflows/windows-build.yml` | After ISCC, `Get-FileHash -Algorithm SHA256` for installer + portable zip; write `SeaLyonMediaManager-{ver}-SHA256SUMS.txt`; upload as artifact. | 1 h | A4 | Release artifact bundle includes checksums file. |
| A8 | `.github/workflows/windows-build.yml` | Add `pytest` step before PyInstaller. Fail build on any test failure or test-collection drop below 637 (Appendix B #8). | 2 h | — | Failing test halts release pipeline. |
| A9 | `build/lyon.iss` | Add `DisableProgramGroupPage=auto`, `WizardImageFile`, `WizardSmallImageFile` for splash branding. Use down-scaled `docs/brand/lyon-splash.png`. | 2 h | — | Installer has branded wizard left bar. |
| A10 | `docs/BUILD.md`, `scripts/README.md` | Update to reflect Inno Setup in CI, tag trigger, local end-to-end repro. | 1 h | A4 | Doc accurate for a fresh contributor. |

**Track A total: ~3 dev-days.**

### Track B — Auto-update (appcast)

**Goal:** App polls a GitHub-Pages-hosted appcast XML at startup, surfaces "update available" non-modally, opens the installer URL in the user's browser. No in-place patching for 1.0.

Appcast URL: `https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml`

Format (WinSparkle-style, no signature for 1.0):
```xml
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>Sea Lyon Media Manager</title>
    <item>
      <title>Version 1.0.0</title>
      <pubDate>...</pubDate>
      <sparkle:version>1.0.0</sparkle:version>
      <sparkle:minimumSystemVersion>10.0</sparkle:minimumSystemVersion>
      <link>https://github.com/.../releases/tag/v1.0.0</link>
      <description><![CDATA[Release notes HTML]]></description>
      <enclosure url="https://.../SeaLyonMediaManager-1.0.0-Setup.exe"
                 sparkle:version="1.0.0"
                 length="..."
                 type="application/octet-stream" />
    </item>
  </channel>
</rss>
```

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| B1 | `lyon/core/updater.py` *(new)* | New module: `check_for_update(appcast_url, current_version) -> UpdateInfo \| None`. `requests.get(...).text`, parse with `defusedxml.ElementTree`, compare `sparkle:version` via `packaging.version`. 10s timeout, full UA. | 4 h | — | Unit-testable with fixture appcasts. Returns `None` when up-to-date. |
| B2 | `lyon/core/updater.py` | Add `UpdateCheckWorker(QObject)` with `finished(UpdateInfo \| None)` signal. | 2 h | B1 | Worker emits at most one signal, terminates cleanly. |
| B3 | `lyon/core/settings.py` | Add `update_check_enabled: bool = True`, `update_appcast_url: str = "https://drshoctopus.github.io/Sea-Lyon-Media-Manager/appcast.xml"`, `last_update_check_ts: int = 0`, `skipped_update_version: str = ""`. | 1 h | — | Settings round-trip. Tests updated. |
| B4 | `lyon/ui/settings_dialog.py` | Add "Updates" group: checkbox "Check for updates automatically", "Last checked: …", "Check now" button. | 2 h | B3 | Toggle persists; "Check now" triggers worker. |
| B5 | `lyon/ui/main_window.py` | On startup (after first-run flow), if `update_check_enabled` and last check > 24 h ago, start `UpdateCheckWorker`. On signal, if `UpdateInfo` returned and `version != skipped_update_version`, show `UpdateAvailableDialog`. | 2 h | B2, B3 | Boot does not block on network. UI never freezes when network is down. |
| B6 | `lyon/ui/update_dialog.py` *(new)* | `UpdateAvailableDialog`: shows new version + release notes HTML; "Download Now" (opens enclosure URL), "Skip This Version" (writes `skipped_update_version`), "Remind Me Later" (close). | 3 h | B5 | All three buttons work. Non-blocking. |
| B7 | `lyon/ui/main_window.py` | Add Help → "Check for Updates…" item; force-show result even when up-to-date. | 1 h | B5 | Manual check surfaces toast on "up to date" or dialog on "available". |
| B8 | `tests/test_updater.py` *(new)* | Unit tests: parse sample appcasts (fixtures under `tests/fixtures/appcast_*.xml`), comparison logic (older/equal/newer/malformed). | 2 h | B1 | All tests green. |
| B9 | `docs/RELEASING.md` *(new)* | Document appcast generation: each release writes a new `<item>` to `appcast.xml`, commits to `gh-pages` branch (or repo root + Pages config), CI uploads it as a release asset. | 1 h | A4 | A new contributor can ship 1.0.1 by editing one file + tagging. |
| B10 | `.github/workflows/windows-build.yml`, `scripts/generate-appcast.py` *(new)* | New step that generates/updates `appcast.xml` from `CHANGELOG.md` + tag info on release publish. | 4 h | A4, E1 | Pushing tag `v1.0.0` produces `appcast.xml` containing that release entry. |

**Track B total: ~3 dev-days.**

### Track C — Legal & Licensing

**Goal:** Ship with EULA, third-party license attribution, real MusicBrainz contact, YouTube acknowledgement gate, privacy policy.

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| C1 | `EULA.txt` *(new, repo root)* | MIT terms + 3-paragraph user-responsibility tail (CD ripping legality, YouTube ToS, DLNA broadcasting, scrobbler privacy). ~150 lines plain text. | 4 h | — | Stakeholder-approved. Installer shows it. |
| C2 | `THIRD_PARTY_NOTICES.txt` *(new, repo root)* | Concatenated license text for every bundled/linked dep: VLC (LGPL-2.1), Qt/PySide6 (LGPL-3 + Qt exception), **ffmpeg essentials (GPL-2+ — bundle effectively GPL)**, libdiscid (LGPL-2.1), Chromaprint/fpcalc (LGPL-2.1), Mutagen (GPL-2+), musicbrainzngs (GPL-2+), yt-dlp (Unlicense), requests (Apache-2), urllib3 (MIT), Pillow (HPND), watchdog (Apache-2), defusedxml (PSF), SQLite (public domain). Each block prefixed with name + version + upstream URL. | 4 h | — | Every shipped binary's license reproduced verbatim. |
| C3 | `lyon/ui/about.py` | Refactor `THIRD_PARTY_NOTICE` to structured list of `(name, version, license, url)` tuples. Add `format_license_summary()` and `licenses_full_text()` returning the bundled notices file. | 2 h | C2 | About module exposes both summary and full text. |
| C4 | `lyon/ui/about_dialog.py` *(new)* | Replace `show_about()`'s `QMessageBox` with `QDialog`: tabs for About, Acknowledgements, Licenses (scroll area with full text), System Info (Python version, Qt version, VLC version, log folder path as clickable link). | 4 h | C3, D2 | Tabbed About dialog renders all three tabs. |
| C5 | `PRIVACY.md` *(new, repo root)* | One-page privacy statement: "Sea Lyon Media Manager does not collect telemetry. Networking happens only on user action (MusicBrainz, podcast fetch, Last.fm scrobble, YouTube search, etc.) and uses contact UA headers per provider terms." List each outbound endpoint. | 3 h | — | Stakeholder-approved. Linked from About. |
| C6 | `lyon/ui/about_dialog.py`, `lyon/ui/main_window.py` | "Privacy Policy" link inside About → Acknowledgements opens bundled `PRIVACY.md` via `QDesktopServices.openUrl`. | 1 h | C4, C5 | Click opens privacy policy in default app. |
| C7 | `lyon/core/settings.py` | Change `musicbrainz_contact` default from `"https://example.invalid/lyon"` to `"https://github.com/DrShoctopus/Sea-Lyon-Media-Manager"`. Add an in-app warning toast on settings load if contact looks like a placeholder (`example.`, `localhost`, empty). | 2 h | — | Default never resolves to placeholder. Toast fires when user has not yet customized. |
| C8 | `lyon/core/podcast.py` | Replace `PODCAST_USER_AGENT` constant with `_podcast_user_agent()` returning `Sea Lyon Media Manager/{version} (+{contact}) Podcast/1.0`. | 1 h | C7 | Outbound podcast requests carry version + contact. |
| C9 | `lyon/core/scrobbler.py` | Add `headers={"User-Agent": _scrobbler_user_agent()}` to both `_SESSION.post` calls. Same UA format as podcast/MB. | 1 h | C7 | Last.fm + ListenBrainz requests carry app UA. |
| C10 | `lyon/core/settings.py` | Add `youtube_acknowledged: bool = False` field. | 0.25 h | — | Setting persisted; round-trip tested. |
| C11 | `lyon/ui/youtube_view.py` | On first activation of YouTube tab and on first open of any download dialog: if `not settings.youtube_acknowledged`, show blocking acknowledgement dialog (1-paragraph disclaimer about ToS / regional law / personal use). Buttons: "I Understand and Accept" (sets flag) / "Cancel" (returns to previous tab). | 3 h | C10 | First entry to YouTube tab gates on dialog. Subsequent uses do not. |
| C12 | `tests/test_settings.py`, `tests/test_first_run.py` | Tests for new fields (`youtube_acknowledged`, `musicbrainz_contact` placeholder warning, `update_check_enabled`). | 2 h | C10, C7, B3 | Round-trip + placeholder detection covered. |

**Track C total: ~4 dev-days.**

### Track D — Crash & Diagnostics

**Goal:** Every error reaches a rotating log file. Help menu lets user open log folder and copy diagnostics bundle. No telemetry.

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| D1 | `lyon/app.py` | Add `_configure_logging()` called at the top of `main()`. Use `logging.handlers.RotatingFileHandler(app_data_dir() / "logs" / "sea-lyon.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")`. Attach `StreamHandler` to stderr at WARNING+. Root logger INFO. Format `"%(asctime)s %(levelname)s %(name)s: %(message)s"`. Create `logs/` if missing. | 2 h | — | Running app produces `sea-lyon.log`. Rotates at 10 MB. No data loss on rotate. |
| D2 | `lyon/app.py` | Install global `sys.excepthook` + `threading.excepthook` logging uncaught tracebacks before defaulting to original. Wire Qt top-level errors → log. | 2 h | D1 | Uncaught exception in worker thread shows up in `sea-lyon.log` with full traceback. |
| D3 | `lyon/core/diagnostics.py` | Add `collect_diagnostics_bundle() -> str`: app version + git sha, Python version, OS version, `run_dependency_checks()` output, last 1 MB of `sea-lyon.log`, last 1 MB of `metadata-diagnostics.log` if present, `settings.json` with secrets redacted (`lastfm_session_key`, `listenbrainz_token`, `theaudiodb_api_key`). | 4 h | D1 | Output ≤ 3 MB. Secret values appear as `<redacted>`. |
| D4 | `lyon/ui/main_window.py` | Help menu: "Open Log Folder" (`QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir)))`) and "Copy Diagnostics to Clipboard" (calls `collect_diagnostics_bundle()`, `QApplication.clipboard().setText(...)`, toast "Diagnostics copied; paste into a support email."). | 2 h | D3 | Both menu items work. Toast confirms copy. |
| D5 | `lyon/ui/about_dialog.py` | Show "Log folder: `<path>`" with an "Open" button + same Copy Diagnostics action. | 1 h | C4, D3 | About → System Info tab tells user where log lives. |
| D6 | `tests/test_logging.py` *(new)* | Tests for `_configure_logging` (rotation, formatter, idempotency) and `collect_diagnostics_bundle` (redaction). | 2 h | D1, D3 | Tests green; rotation verified with > 10 MB write. |
| D7 | `lyon/app.py` | Make `_configure_logging` idempotent (skip if root logger already has a `RotatingFileHandler`). | 1 h | D1 | pytest imports `lyon.app` repeatedly without duplicate log entries. |

**Track D total: ~2 dev-days.**

### Track E — Release Engineering

**Goal:** A repeatable, tag-triggered build producing a hash-checked, downloadable installer with public release notes.

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| E1 | `CHANGELOG.md` *(new, repo root)* | "Keep a Changelog" format. Sections: `## [Unreleased]`, `## [1.0.0] — 2026-XX-XX`. Fold in everything since 0.8.0 using `git log 0.2.0..HEAD`. | 3 h | — | 1.0.0 entry has Added / Changed / Fixed sections. |
| E2 | `lyon/__init__.py` | Bump `__version__ = "1.0.0"`. **Last** task on the release commit. | 0.1 h | F-track complete | Single source of truth updated. |
| E3 | `requirements.txt`, `requirements.in` *(new)* | Pin transitive deps. Generate with `pip-compile` from a 1-line `requirements.in`, or `pip freeze` after clean venv install. Commit both. | 2 h | — | `pip install -r requirements.txt` in clean env reproduces versions. |
| E4 | `README.md` | Remove macOS/Linux from advertised surface (lines 15, 71, 212, 230, 275). Keep one sentence that source runs cross-platform for devs. Add "Windows 10/11 64-bit only" at top. Link to download page, SmartScreen note, CHANGELOG. | 3 h | C5, F3 | README accurately reflects supported surface. SmartScreen guidance present. |
| E5 | `lyon/core/media_keys.py` | macOS branch is now dead code. Leave as `if sys.platform == "darwin": pass`-only stub (less churn than full removal). | 0.5 h | — | No platform-conditional dead code reported by future ruff/mypy. |
| E6 | `.github/workflows/windows-build.yml` | Add `on: push: tags: ['v*.*.*']` trigger alongside `workflow_dispatch`. On tag push, auto-create GitHub Release (`softprops/action-gh-release@v2`) with installer, portable zip, SHA256SUMS, CHANGELOG section attached. | 4 h | A4, A7, E1 | `git tag v1.0.0 && git push origin v1.0.0` produces public draft Release. |
| E7 | `.github/workflows/windows-build.yml` | Add release-notes extraction via `scripts/changelog-section.py` (new). Feed output into Release body. | 2 h | E1, E6 | Release body matches CHANGELOG section. |
| E8 | `scripts/changelog-section.py` *(new)* | ~30-line Python: read `CHANGELOG.md`, find heading matching tag, print section. | 1 h | E1 | Output identical to manual CHANGELOG read. |
| E9 | `docs/RELEASING.md` *(new)* | Step-by-step: "Update CHANGELOG → bump version → tag → push → wait for CI → smoke-test artifact → publish draft Release → update appcast.xml". | 2 h | A4, B9, B10, E6 | A second engineer can ship 1.0.1 by following this doc. |
| E10 | `lyon/ui/main_window.py` (or `lyon/app.py`) | One-time SmartScreen advisory toast on first launch of installer-installed build: "This app is unsigned; Windows SmartScreen may have warned you. See README for details." Suppress in dev/source runs. Persist a `smartscreen_advisory_shown` flag in settings. | 2 h | A2, A3 | Toast only fires once per install. |

**Track E total: ~2.5 dev-days.**

### Track F — Quality Gates (docs + manual)

**Goal:** A documented, repeatable test plan we sign off before tagging.

| ID | Files | Change | Effort | Depends | Acceptance |
|---|---|---|---|---|---|
| F1 | `docs/RELEASE_CHECKLIST.md` *(new)* | Per-release smoke-test checklist. Sections: "Fresh user (no %APPDATA%)", "Upgrade from 0.8.0", "Win10 22H2", "Win11 23H2", "HiDPI 100%/125%/150%/175%", "4K display", "Audio CD detection + rip", "DLNA cast", "YouTube audio + video download", "Crossfade across queue", "EQ audible". Each item is a tick-box with expected result. | 3 h | — | One sheet per release, signed off before tagging. |
| F2 | `docs/HIDPI_MATRIX.md` *(new)* | Matrix of (resolution × DPI scale) the app is expected to render correctly. Notes on known issues. | 2 h | — | Anyone can re-run and produce comparable results. |
| F3 | `docs/SMARTSCREEN_NOTES.md` *(new, linked from README + GitHub Releases body)* | User FAQ: "Why does Windows warn me? Click More info → Run anyway. We're working on signing for 1.1." Include screenshot. | 1 h | A4 | Linked from README and from Releases body via E7. |
| F4 | Manual run | Run F1 on Win10 VM + Win11 VM. Capture pass/fail/notes. File any blocker bugs as `release-blocker` issues. | 2 hd | A4 | Both VMs green or issues documented in CHANGELOG. |
| F5 | Manual run | Verify uninstaller cleans `%APPDATA%` when user agrees and leaves it intact when user declines. | 1 h | A2 | Both branches tested. |
| F6 | Manual run | Verify auto-update flow against a "fake 1.0.1" appcast (edit XML, point app to it via settings override). | 1 h | B5, B6, B7 | Update dialog appears, opens browser to download URL. |
| F7 | Manual run | Verify "Copy Diagnostics" output contains redacted secrets and no PII beyond library paths. | 0.5 h | D3 | Confirmed. |

**Track F total: ~4 dev-days (mostly manual).**

---

## Section 3 — Sequencing / Calendar

Single dev, ~5 productive dev-days per week, ≈4 weeks. Tracks overlap because they touch different files.

```
Week 1 — Foundations
  A5, A6  Hash-pinning + fpcalc pin in workflow ........ 0.5 d
  A8      pytest gate in CI ........................... 0.25 d
  D1, D2  RotatingFileHandler + excepthook ............ 0.5 d
  D7      idempotent logging ......................... 0.25 d
  C7      MusicBrainz contact + placeholder warning .. 0.25 d
  C8, C9  Podcast + scrobbler UA cleanup ............. 0.5 d
  E1      CHANGELOG.md initial fill-in ............... 0.5 d
  E3      Pin transitive deps ........................ 0.25 d
  A9      Inno Setup branding ........................ 0.25 d
  C1      EULA draft ................................. 0.5 d
  C5      PRIVACY.md draft ........................... 0.25 d
  C2      THIRD_PARTY_NOTICES.txt assembly ........... 0.5 d
        ────────────────
        ~4.5 d  (ends Friday week 1)

Week 2 — Installer + About + YouTube gate
  A1, A2, A3   lyon.iss EULA/notices/uninstall/registry  0.75 d
  A4      ISCC in CI ................................. 0.5 d
  A7      SHA256SUMS step ............................ 0.25 d
  A10     BUILD.md doc update ........................ 0.25 d
  C3, C4  About dialog refactor ...................... 0.75 d
  C6      Privacy link wiring ........................ 0.25 d
  C10     youtube_acknowledged setting ............... 0.1 d
  C11     YouTube acknowledgement dialog ............. 0.5 d
  C12     Settings tests update ...................... 0.25 d
  D3, D4, D5  Diagnostics bundle + Help actions ...... 0.75 d
  D6      Logging tests .............................. 0.25 d
        ────────────────
        ~4.6 d

Week 3 — Auto-update + Release engineering
  B1, B2  Updater module + worker .................... 0.75 d
  B3      Settings additions ......................... 0.25 d
  B4      Settings dialog "Updates" group ............ 0.25 d
  B5      MainWindow startup hook .................... 0.25 d
  B6      UpdateAvailableDialog ...................... 0.5 d
  B7      Help → Check for Updates ................... 0.25 d
  B8      Updater tests .............................. 0.25 d
  B9      Releasing doc (appcast part) ............... 0.25 d
  B10     CI appcast generation ...................... 0.5 d
  E6, E7  Tag-triggered release ...................... 0.75 d
  E8      changelog-section.py ....................... 0.25 d
  E9      RELEASING.md (full) ........................ 0.25 d
  E10     SmartScreen first-run toast ................ 0.25 d
  E4      README rewrite ............................. 0.5 d
  E5      media_keys macOS branch cleanup ............ 0.1 d
  Cut v0.9.0-rc1 tag (dry-run pipeline) .............. 0.25 d
        ────────────────
        ~5.5 d

Week 4 — Quality gates + ship
  F1, F2, F3   Test plan docs ....................... 0.75 d
  F4      Win10 VM run ............................... 1 d
  F4      Win11 VM run ............................... 1 d
  F5, F6, F7   Targeted checks ...................... 0.5 d
  Fix-up buffer for bugs from F4 ..................... 1 d
  E2      Bump __version__ to 1.0.0 .................. 0.1 d
  Tag v1.0.0, publish release, write announcement .... 0.5 d
        ────────────────
        ~4.85 d
```

**Critical path:**
1. C1 EULA approval — blocks A1 (installer EULA page) and A4 (CI compile).
2. C2 THIRD_PARTY_NOTICES.txt — blocks A1 and C3/C4.
3. A4 Inno Setup in CI — blocks F4 manual smoke and B10 appcast generation.
4. B1/B2 updater module — blocks B5–B10.
5. F4 manual smoke tests — blocks tagging 1.0.

**Internal RC cut:** `v0.9.0-rc1` at end of Week 3 dry-runs the whole pipeline. If it lands clean, 1.0 is a re-tag + version bump.

---

## Section 4 — Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SmartScreen scares away ~50% of downloaders | High | High user-acquisition hit | F3 SmartScreen doc + in-app first-run note (E10) + clear download-page instructions. Budget OV cert for 1.1. |
| EULA decision delayed | Medium | Slips Week 2 | EULA drafted Week 1; stakeholder review by Mon Week 2. Fallback ready: MIT-only screen + 1-paragraph "use at own risk" tail. |
| ffmpeg license tainting (essentials = GPL) | Medium | Legal grey for future commercial path | Accepted for 1.0; GPL text in notices. Plan strict-LGPL swap for 1.1. |
| Inno Setup per-user vs per-machine UAC differences | Medium | Support traffic spike | Test both modes in F4. Document in F3. |
| Hash-pinning catches a real upstream version bump | Low | Tagged release fails | `build/manifest.json` + clear failure messages. Document "update the manifest" in RELEASING.md. |
| Auto-update appcast URL changes after 1.0 ships | Low | Hard to fix in old clients | Use stable GitHub Pages URL from day 1. Hard to migrate; document immutability. |
| Crash in startup before logging is configured | Low | Silent crash | `_configure_logging` first in `main()`; wrap in try/except printing to stderr. |
| Unsigned binary → AV false positive | Medium | Quarantined installer | Submit binary to Microsoft Defender + sample-submit to AV vendors as "false positive" pre-1.0. Plan in F4. |
| Pinned `requirements.txt` drifts from CI image | Low | Build break | E3 done in same venv as CI. Verify before tagging. |

---

## Section 5 — Out of Scope / Post-1.0 Markers

Explicitly **not** in this plan; do not implement before tagging 1.0:

- **Code-quality CI gates** (ruff, black, mypy, pyright). → Post-1.0 (target 1.1).
- **Module splits** (`library_view.py`, `metadata.py`, `library.py`, `dlna_server.py`, `ripper.py`). → Post-1.0.
- **SQLite migration framework**. → Post-1.0 (before 1.2 / before any schema change).
- **Settings JSON `schema_version`**. → Post-1.0 (1.1).
- **Sentry / opt-in telemetry.** Explicitly scoped out — local-only crash reporting. Never unless user opts in.
- **Code signing (Authenticode).** → 1.1, OV cert budget.
- **WinSparkle native dep / in-place auto-install.** → Post-1.0.
- **macOS .dmg / Linux .AppImage.** Scoped out; source-only on those platforms.
- **SQL parameterization audit / smart-playlist injection check.** → Recommended Week 1 buffer (~2 h grep). If suspicious code found, file release-blocker.
- **Defusedxml audit across all XML parsing.** → Week 1 buffer (~30 min `grep -rn "ElementTree\|xml.etree\|xml.dom" lyon/`).
- **Crossfade soak test.** → Post-1.0 unless F4 surfaces regression.
- **Strict-LGPL ffmpeg swap.** → 1.1.

---

## Section 6 — Critical Files for Implementation

Most-touched files:

- `build/lyon.iss` — installer (Track A1–A3, A9).
- `.github/workflows/windows-build.yml` — CI pipeline (Tracks A4–A8, E6–E7, B10).
- `lyon/app.py` — entry point (D1, D2, D7).
- `lyon/ui/main_window.py` — Help menu, About wiring, first-run flow, startup update check (D4, B7, C4, B5).
- `lyon/core/settings.py` — new fields (B3, C7, C10).

New files to create:
- `lyon/core/updater.py`
- `lyon/ui/update_dialog.py`
- `lyon/ui/about_dialog.py`
- `CHANGELOG.md`
- `EULA.txt`
- `PRIVACY.md`
- `THIRD_PARTY_NOTICES.txt`
- `docs/RELEASING.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/SMARTSCREEN_NOTES.md`
- `docs/HIDPI_MATRIX.md`
- `scripts/generate-appcast.py`
- `scripts/changelog-section.py`
- `tests/test_updater.py`
- `tests/test_logging.py`
- `tests/fixtures/appcast_*.xml`
- `build/manifest.json`
- `requirements.in`

Supporting files for read-only justification but small touches: `lyon/ui/about.py`, `lyon/core/diagnostics.py`, `lyon/ui/first_run_dialog.py`, `lyon/core/podcast.py`, `lyon/core/scrobbler.py`, `lyon/ui/youtube_view.py`.

---

*End of plan.*
