# Changelog

All notable changes to Sea Lyon Media Manager will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Rotating application log under `%APPDATA%\LyonMusicManager\logs\sea-lyon.log` (10 MB × 5 backups).
- Global uncaught-exception logging (main thread + worker threads) so crashes leave a trail.
- Versioned, contact-bearing `User-Agent` header on outbound podcast feed fetches and Last.fm / ListenBrainz submissions.
- Placeholder-detection helper for the MusicBrainz contact setting.

### Changed
- Default MusicBrainz contact now points at the project's GitHub URL instead of `example.invalid`.

### Planned for 1.0.0
- Inno Setup installer wired into CI with bundled VLC + ffmpeg + fpcalc.
- SHA-256 verification of every binary download in the GitHub Actions workflow.
- Auto-update check against a GitHub Pages appcast.
- Tabbed About dialog with full third-party license texts.
- EULA, privacy policy, and YouTube acknowledgement gate.
- Help → Open Log Folder / Copy Diagnostics actions.
- Windows-only release; macOS / Linux remain source-only.
- See `IMPLEMENTATION_PLAN_1.0.md` for the full release plan.

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
