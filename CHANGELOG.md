# Changelog

All notable changes to Sea Lyon Media Manager will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- YouTube downloads can optionally use a signed-in browser session for
  age-restricted videos the user is authorized to access. The opt-in setting
  stores only the selected browser name and passes it to yt-dlp's
  browser-cookie loader. Authenticated downloads avoid yt-dlp's fragile
  `web_safari` YouTube player client path.
- YouTube downloads now enable Deno/Node JavaScript challenge solving via
  `yt-dlp-ejs`, prefer bundled/Homebrew runtime paths when available, and
  surface a clear runtime/solver message when YouTube signature solving
  blocks a download.

### Fixed
- macOS: random audio pops during playback in the packaged app. A
  Finder/Dock-launched `.app` is eligible for App Nap, whose timer
  coalescing and QoS throttling intermittently starved libVLC's audio
  thread (terminal and from-source launches are exempt, which is why only
  the installed DMG reproduced it). Lyon now holds an `NSProcessInfo`
  latency-critical activity assertion while audio is playing — the
  supported, reliable opt-out — released when paused/stopped. The
  `NSAppSleepDisabled` Info.plist key is kept as a secondary hint.

### Changed
- Privacy, legal, build, README, and in-app knowledge-base documentation
  now describe YouTube browser-session cookie handling, packaged Deno
  runtime staging, local Deno/Node JavaScript challenge solving, and the
  bundled `yt-dlp-ejs` solver package.
- Bundled libVLC upgraded 3.0.21 → 3.0.23 (Windows and macOS) to match the
  known-good system runtime; the About dialog and third-party notices were
  updated accordingly.

## [1.0.0] — 2026-06-04

Sea Lyon Media Manager 1.0.0 is the first public release. It ships a
Windows 10 / 11 x64 installer and portable zip. macOS Apple Silicon is
included only if the macOS workflow artifacts and physical smoke test on
the oldest advertised macOS version pass before publication; otherwise
macOS remains a clearly labeled post-1.0 milestone.

### Added — Release packaging
- Windows Inno Setup installer with EULA, third-party notices,
  uninstall data-retention prompt, SmartScreen guidance, HKCU updater
  registry entries, and branded installer artwork.
- Windows portable zip for users who prefer extraction over install.
- macOS Apple Silicon DMG workflow with arm64 PyInstaller bundle,
  bundled libVLC / ffmpeg / fpcalc / libdiscid, Developer ID signing
  and notarization when secrets are configured, and unsigned fallback
  documentation when they are not.
- Sparkle-style appcast generation for the browser-handoff updater,
  including platform-specific enclosures so Windows builds do not offer
  macOS DMGs and macOS builds do not offer Windows installers.
- SHA-256 manifests for release artifacts.
- `docs/RELEASING.md` with the tag, workflow, smoke-test, publish, and
  appcast verification procedure.
- `docs/RELEASE_CHECKLIST.md` with the manual 1.0 smoke-test checklist
  for Windows 10, Windows 11, Windows upgrade install, and conditional
  macOS Apple Silicon verification.

### Added — User-facing app features
- Local audio and video library management backed by SQLite.
- libVLC audio playback with queue restore, shuffle/repeat,
  crossfade, gapless playback, ReplayGain, equalizer, media keys,
  Now Playing, album details, artwork, and lyrics.
- CD detection, Audio CD playback, metadata lookup, ripping, optional
  CUETools DB AccurateRip verification, and library import after rip.
- Podcast subscriptions, OPML import, internet radio, YouTube search
  and download via yt-dlp, and DLNA / UPnP cast and media serving.
- Runtime diagnostics, rotating logs, About / Acknowledgements /
  Licenses / System Info dialogs, privacy policy, EULA, and third-party
  notices.
- Browser-handoff update checks from a GitHub Pages appcast, with
  release notes, skip/remind-later controls, HTTPS-only appcast
  settings, and HTTPS-only update links.

### Changed
- Public documentation now treats Windows x64 as the mandatory 1.0
  package and macOS Apple Silicon as conditional on successful CI and
  physical smoke testing on the oldest macOS version advertised for the
  release.
- README, build docs, release checklist, changelog, app version, and
  release workflow naming now agree on `1.0.0`.
- The appcast URL setting is normalized to HTTPS and unsafe update
  dialog links are ignored instead of being handed to the OS.
- Smart playlist limits are bound as SQL parameters instead of being
  interpolated into the query string.

### Fixed
- Gapless playback now cancels stale prebuffers on seek and pause.
- Gapless promotion revalidates the prebuffered track before swapping
  backends, including shuffle mode without re-rolling the random next
  track at promotion time.
- Removed temporary duplicate-tag-read diagnostics from the library scan
  hot path.
- Replaced representative silent exception handlers with debug or
  warning logs so field failures leave a diagnostics trail.

### Known issues
- The Windows 1.0 installer is unsigned; Windows SmartScreen can warn
  until Authenticode signing is available. Verify the SHA-256 manifest
  before running the installer.
- The bundled ffmpeg essentials build links GPL components, so the
  combined installer is GPL-tainted with respect to ffmpeg. A
  strict-LGPL ffmpeg option remains post-1.0 work.
- macOS artifacts must not be advertised unless the DMG is built,
  smoke-tested on the oldest advertised macOS version, and either
  notarized or explicitly documented as unsigned.
- The updater is intentionally notification-and-download only; it does
  not perform in-place updates or verify artifact signatures.

## [0.9.0-rc1] — 2026-05-24

Release candidate for the public v1.0.0 ship. **Windows 10 / 11 (64-bit)
only.** This RC exists to dry-run the tag-triggered CI pipeline,
installer, appcast generation, and SHA-256 attestation before the real
v1.0 tag. Do not advertise this build outside the project; it is for
release-engineering validation.

### Added — Release engineering
- Inno Setup installer wired into CI (`build/lyon.iss`): EULA license
  page, third-party notices page, `%APPDATA%` cleanup prompt at
  uninstall (default No), HKCU registry entries for the updater
  (`InstalledVersion` / `InstallPath` / `AppcastUrl`), and a branded
  wizard image from `docs/brand/lyon-splash.png`.
- GitHub Actions release pipeline that hash-verifies ffmpeg / libdiscid
  / VLC / fpcalc downloads, runs the full pytest suite as a gate
  (`PYTEST_FLOOR` aborts the build if test count drops), compiles the
  installer with ISCC, emits a `SHA256SUMS.txt` manifest, and (on
  `v*.*.*` tag pushes) creates a draft GitHub Release with installer +
  zip + manifest + appcast attached.
- `scripts/changelog-section.py` extracts one CHANGELOG section by
  version for use as the GitHub Release body.
- `scripts/generate-appcast.py` builds the Sparkle-style `appcast.xml`
  from a CHANGELOG snippet plus installer URL + size; preserves up to
  10 historical items.
- `docs/RELEASING.md` step-by-step release procedure (changelog →
  bump → tag → wait → smoke-test → publish → push appcast to
  `gh-pages`).
- `docs/RELEASE_CHECKLIST.md` 14-section Win10 + Win11 tick-box smoke
  test sheet covering installer, first-run, audio, library, CDs, video,
  YouTube, podcasts, DLNA, auto-update, diagnostics, uninstall, HiDPI,
  and stress.
- `docs/HIDPI_MATRIX.md` resolution × scale matrix + 14 per-screen
  visual checks.
- `docs/SMARTSCREEN_NOTES.md` user-facing FAQ for the unsigned-installer
  Windows SmartScreen warning, including the `Get-FileHash` verification
  recipe.
- `docs/BUILD.md` rewritten to document the new CI flow, hash-pinning,
  ISCC step, registry layout, and reproducible-build notes.

### Added — Legal & licensing
- `EULA.txt` — MIT terms plus a three-paragraph user-responsibility
  tail covering CD ripping legality, YouTube ToS, DLNA broadcasting,
  and scrobbler privacy. Shown on the installer's license page.
- `PRIVACY.md` — full outbound-endpoint inventory. No telemetry.
  Documents the diagnostics-bundle redaction policy.
- `THIRD_PARTY_NOTICES.txt` — per-dependency license attribution for
  VLC, Qt/PySide6, ffmpeg (essentials build, GPL-tainted), libdiscid,
  Chromaprint/fpcalc, Mutagen, musicbrainzngs, yt-dlp, requests,
  defusedxml, watchdog, pyacoustid, Pillow, and SQLite.

### Added — App
- Rotating application log at
  `%APPDATA%\LyonMusicManager\logs\sea-lyon.log` (10 MB × 5 backups).
- Global `sys.excepthook` + `threading.excepthook` route uncaught
  exceptions through the logging system so crashes leave a trail.
- `lyon.core.diagnostics.collect_diagnostics_bundle()` assembles a
  multi-section text bundle (versions, dependency checks, log tails,
  redacted settings) for support requests. Redacts
  `lastfm_session_key`, `listenbrainz_token`, and
  `theaudiodb_api_key`.
- Help menu additions: Open Log Folder, Copy Diagnostics to
  Clipboard, Check for Updates… (manual update check).
- Tabbed About dialog (`lyon/ui/about_dialog.py`) with About /
  Acknowledgements / Licenses / System Info tabs. Acknowledgements
  links to Privacy Policy and EULA via `QDesktopServices`; System Info
  shows the log folder path with an "Open" button and a Copy
  Diagnostics shortcut.
- Structured `ATTRIBUTIONS` + `NETWORK_SERVICES` lists in
  `lyon/ui/about.py`; `format_license_summary()` and
  `licenses_full_text()` helpers used by the new dialog.
- YouTube acknowledgement gate
  (`lyon/ui/youtube_acknowledgement_dialog.py`). Modal disclaimer
  appears on the first YouTube tab activation and the first download
  dialog open. Setting persisted as `settings.youtube_acknowledged`.
- One-time SmartScreen advisory toast on the first launch of an
  installer-installed build, gated by
  `settings.smartscreen_advisory_shown`. Suppressed in source / dev
  runs via `sys.frozen` check.
- Auto-update plumbing (`lyon/core/updater.py`,
  `lyon/ui/update_dialog.py`): Sparkle 2.0 appcast parser with version
  comparator, `UpdateCheckWorker` QThread, daily startup check
  (≥24 h interval), non-modal `UpdateAvailableDialog` with Download
  Now / View Release Page / Skip This Version / Remind Me Later, and
  Help → Check for Updates… for manual checks.
- Settings → Updates tab: toggle, appcast URL, last-checked timestamp,
  "Check now" button, "Stop skipping" affordance when a version was
  skipped.

### Added — Networking hygiene
- `lyon/core/user_agent.py` — shared `component_user_agent()` and
  `musicbrainz_user_agent()` helpers ensure every outbound request
  carries `Sea Lyon Media Manager/{version} (+{contact})` plus a
  component suffix.
- Podcast feed fetches, Last.fm + ListenBrainz scrobbles, and the
  updater all use the helper. Default contact is the project's GitHub
  URL (was `https://example.invalid/lyon`).
- `is_placeholder_contact()` helper detects unconfigured contact
  strings so the UI can warn before publishing them.
- `lyon/app.py` configures logging idempotently at startup; pytest no
  longer double-attaches the rotating file handler.

### Added — CI quality gates
- `pytest` runs before PyInstaller; the build aborts on any failure
  or if the collected test count drops below `PYTEST_FLOOR` (currently
  680). This catches silently-skipped tests.
- Hash pinning for ffmpeg / libdiscid / VLC downloads matches the
  logic in `scripts/build-windows.ps1`; fpcalc is pinned to a known
  Chromaprint version (`1.5.1`) so the build is reproducible.
- 47 new tests across `tests/test_settings.py`,
  `tests/test_logging_and_diagnostics.py`, and `tests/test_updater.py`
  covering settings round-trip, log rotation, excepthook routing,
  diagnostics redaction, appcast parsing, the version comparator, the
  worker timeout, and HTTP error / network-error handling.

### Changed
- README rewritten Windows-only. Removes mac / Linux from the
  advertised surface, adds prominent Windows 10 / 11 64-bit banner,
  Downloads section, SmartScreen guidance link, auto-update notes,
  YouTube acknowledgement gate documentation, and legal-document
  links.
- `lyon/ui/main_window.py` Help menu restructured into Knowledge Base
  / Library Statistics / Runtime Diagnostics / **Open Log Folder /
  Copy Diagnostics / Check for Updates…** / About.
- `lyon/ui/about.py` refactored from string constants to a structured
  `Attribution` dataclass list so the About dialog can render
  per-component metadata.
- Settings UI gains a dedicated Updates tab between DLNA and About.
- `lyon/core/media_keys.py` docstring clarifies the macOS path is
  best-effort and not part of the supported v1.0 surface.
- `requirements.txt` carries a header explaining how to regenerate
  with `pip-compile --generate-hashes` from `requirements.in`.

### Fixed
- MusicBrainz contact placeholder (`https://example.invalid/lyon`) no
  longer leaks into outbound requests; default is now the project's
  GitHub URL.
- Knowledge-base text no longer references the obsolete
  `PODCAST_USER_AGENT` symbol.
- Test fixtures for `tests/test_main_window_integration.py` set
  `youtube_acknowledged=True` so the modal gate doesn't hang the
  headless test runner.

### Known issues
- Installer is **unsigned**; SmartScreen will warn on first run. See
  `docs/SMARTSCREEN_NOTES.md`. Authenticode signing is planned for
  v1.1.
- The bundled ffmpeg "essentials" build links libx264 / libx265
  (GPL-2+), making the combined installer effectively GPL with
  respect to ffmpeg. A strict-LGPL ffmpeg swap is planned for v1.1.
- Transitive Python dependency hashes are not yet pinned in
  `requirements.txt`. Run `pip-compile --generate-hashes` from
  `requirements.in` on a Windows venv before tagging v1.0.0.
- `appcast.xml` push to `gh-pages` is manual in this RC; automation
  lands in v1.1.

## [0.8.0] — development snapshot (LMM-DEV branch)

This is the feature-complete development snapshot of the v0.8.0 plan. It
preceded the v1.0 release-engineering pass and was not publicly released.

### Added
- 10-band equalizer with presets, custom curves, and preamp slider.
- Crossfade and gapless playback across queue transitions.
- Sleep timer.
- ReplayGain analysis + track / album modes with preamp and clip prevention.
- Podcast subscriptions with RSS / Atom / OPML import and background refresh.
- Internet radio (M3U / PLS) with saved station list.
- YouTube search + audio / video download via yt-dlp, with format and quality picker.
- DLNA / UPnP cast to smart TVs and AV receivers.
- DLNA media server.
- AcoustID fingerprinting (Chromaprint / fpcalc).
- Last.fm + ListenBrainz scrobbling with offline auth flow.
- CUE sheet parsing for single-file FLAC + CUE albums.
- Knowledge-base / F1 help browser.
- Library statistics dialog.
- Runtime diagnostics dialog reporting ffmpeg / VLC / discid / Python paths.
- First-run setup wizard.
- Settings dialog reorganised into tabs.
- Branding pass: dark Windows Media Player–inspired theme, splash, app icons.
- Windows build automation: PyInstaller spec, PowerShell build script, GitHub Actions workflow.

### Fixed
- DLNA discovery, browsing, and shutdown correctness.
- Cast transport routing regressions.
- Scrobble, shuffle, gapless, and DLNA correctness bugs.
- Playback transition and scrobble correctness.
- AcoustID erasure, video card ordering, backfill race.
- Podcast playback snap-back.
- Now-playing background blur debouncing.
- Multiple Qt object-ownership leaks in crossfade backends and timers.

### Performance
- Lazy-load Now Playing, Video Player, Disc/Rip, and other low-traffic tabs.
- Async album artwork loading.
- Reuse scrobbler HTTP session.
- Reduce VLC position polling while paused.
- Batch CUE indexing commits; page missing fingerprint queries.
- Metadata caching step.
- SQL `GROUP BY` consolidation; TransportBar widget extraction; async hash scan.
- `QStandardItemModel` → `QAbstractTableModel` migration for the track list.

## [0.2.0] — 2026 (early development tag)

First tagged development snapshot. Library, playback, CD ripping, and core metadata
providers (MusicBrainz, CTDB, TheAudioDB, Cover Art Archive, LRCLIB).
