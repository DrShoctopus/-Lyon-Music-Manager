# Sea Lyon Media Manager — Product Report
**Version:** 0.5.0 · **Date:** 2026-05-17 · **Branch:** LMM-DEV

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Current Feature Completeness Audit](#2-current-feature-completeness-audit)
3. [Competitive Analysis](#3-competitive-analysis)
4. [Gap Analysis](#4-gap-analysis)
5. [Implementation Plan](#5-implementation-plan)
6. [Development Roadmap](#6-development-roadmap)

---

## 1. Executive Summary

Sea Lyon is a Windows-first desktop media manager built on Python + PySide6, libVLC, and SQLite. Its core value proposition is an all-in-one CD ripping, local library management, and media playback experience with YouTube integration. At v0.5.0, the product is approximately **87% complete** for its stated scope — core functionality is solid, stable, and production-ready. Previous P0/P1 bugs identified in a 2026-05-15 code review have all been resolved in subsequent commits. The remaining gaps are feature gaps rather than stability blockers.

**Strengths to build on:**
- Mature audio playback engine with crossfade, equalizer, and smart playlists
- Best-in-class CD ripping metadata pipeline (CUETools DB → MusicBrainz → TheAudioDB)
- Optical disc support beyond ripping (CD/DVD/VCD playback)
- Integrated YouTube download with library import
- Solid threading model: all worker lifecycles properly managed with shutdown/join patterns

**Priority issues:**
- No ReplayGain, no batch tag editor, no output device selection
- UI density and accessibility need improvement before wider distribution
- No network/remote access features (DLNA, mobile companion)
- Library browsing lacks album grid and sortable columns

---

## 2. Current Feature Completeness Audit

### 2.1 Feature Scorecard

| System | Completeness | Stability | Notes |
|--------|:-----------:|:---------:|-------|
| **SQLite Library** | 95% | Stable | v7 schema, 7 migrations, full-text search |
| **Audio Playback** | 100% | Stable | Crossfade, shuffle, repeat, queue restore |
| **Equalizer** | 100% | Stable | 10-band + preamp, 10 presets, custom save |
| **Smart Playlists** | 90% | Stable | SQL rule builder; minor UI operator gaps |
| **CD Detection & Ripping** | 90% | Stable | No CUE sheet support; AccurateRip FLAC-only |
| **Metadata Lookup** | 95% | Stable | Multi-provider fallback chain |
| **Tag Writing** | 100% | Stable | All major formats + embedded art |
| **YouTube Integration** | 85% | Stable | No resume; format limited to yt-dlp support |
| **Video Playback** | 90% | Mostly stable | No resume tracking, no network streams |
| **Optical Disc Playback** | 100% | Stable | CD/DVD/VCD via VLC MRL |
| **Settings & Persistence** | 90% | Stable | Queue restore; weak path validation |
| **Media Keys** | 100% | Stable | macOS only; graceful no-op elsewhere |
| **Diagnostics** | 100% | Stable | Runtime checks for all deps |
| **UI Transport** | 85% | Stable | Functional but dense and low-contrast |
| **Library Browsing** | 80% | Stable | No album grid, no sortable columns |
| **Duplicate Detection** | 70% | Stable | Title+artist only; no hash/fingerprint |

**Overall: ~82% complete for stated v0.5 scope**

---

### 2.2 Detailed System Analysis

#### Library Management
- SQLite backend at platform app-data path; schema version 7 with clean migration chain
- Supports audio (FLAC, MP3, M4A, AAC, OGG, Opus, WAV, AIFF, WMA) and video (MP4, MKV, WebM, AVI, MOV)
- Incremental scan with file-size + mtime-ns change detection
- Full-text search across title, artist, album, album_artist with smart fallbacks
- Browse: genre, artist, album, track, playlists, smart playlists, recently added/played, most played, top rated
- Per-track: rating (0–5), liked flag, play count, last played, grouping tag, disc ID
- Folder artwork detection (cover.jpg / folder.jpg / front.jpg)
- **Gap:** No acoustic fingerprinting; duplicate detection limited to normalized title + artist string match

#### Audio Playback Engine
- libVLC backend with factory pattern for test substitution
- Complete transport: play, pause, stop, seek, previous/next with bounds checking
- Repeat modes: OFF, ALL, ONE; shuffle mode
- Crossfade with configurable overlap (0 = disabled); per-instance fade-in/out timers
- Auto play-count increment on completion (library-linked tracks only)
- Queue load/save on startup/shutdown
- **Complete — no gaps**

#### CD Ripping Pipeline
- Windows-only disc detection via Win32 APIs; libdiscid for MusicBrainz TOC disc IDs
- Output formats: FLAC (compression 0–8), MP3, AAC, Opus, OGG, ALAC, WAV, AIFF, WMA
- Organized output: `<Artist>/<Year> - <Album>/<NN - Title>.<ext>`
- Per-track checkbox selection; progress bars; cancellation; failure logs
- AccurateRip v1 verification via CUETools DB (optional, FLAC only)
- Auto-import to library after each track; eject option
- **Previously fixed bugs (all resolved as of current branch):**
  - libdiscid DLL handle retained in `_DLL_DIRECTORY_HANDLES`; `close_dll_handles()` called on shutdown ✓
  - Rip cancellation uses 0.1s poll loop; `_cleanup_partial()` called on all cancel/error paths ✓
  - CTDB verification streams PCM in 64 KB chunks via bounded queue; no whole-track memory spike ✓

#### Metadata Pipeline
- Lookup order: CUETools DB TOC → MusicBrainz → TheAudioDB enrichment
- Cover Art Archive integration via MBID; 5 MB artwork size cap
- MusicBrainz rate-limited (≤1 req/sec, respects ToS)
- HTTP session pooling; comprehensive error handling; diagnostics log
- **Gap:** No existing-file "Identify Album" workflow; no batch tag editor; no local fingerprinting

#### YouTube Integration
- yt-dlp backend; audio (FLAC, MP3) and video (MP4, MKV, WebM) formats
- Thumbnail embedding; subtitle download and embedding; library auto-import
- **Previously fixed bugs (all resolved as of current branch):**
  - Search workers: blocked from starting a second search while one runs; `shutdown()` joins/terminates on close ✓
  - Download dialog: `closeEvent` cancels worker and ignores the close until thread exits ✓
  - yt-dlp `ImportError`: both `error` and `download_finished` signals emitted; UI re-enables itself ✓

#### Video & Disc Playback
- libVLC video player with local video catalog sidebar and thumbnail cards
- DVD/VCD launch via VLC; CDDA track selection per track
- Playback controls: play/pause/stop, seek, volume, mute, 0.25×–2× speed, audio track, subtitle track, external subtitle load, snapshot
- Fullscreen with keyboard controls and OSD feedback; auto-pause on tab switch
- **Gaps:** No per-video resume position; no subtitle delay/sync controls; no network stream (URL/IPTV); no theater/10-foot mode

---

## 3. Competitive Analysis

### 3.1 Segment Leaders Overview

The desktop media manager market has four distinct tiers with different value propositions:

| Product | Platform | Model | Core Strength |
|---------|----------|-------|---------------|
| **MusicBee** | Windows | Free | Best-in-class library management; highly configurable |
| **MediaMonkey** | Windows | Freemium | Device sync + automation; power-user scripting |
| **foobar2000** | Windows | Free | Audiophile-grade playback; minimal footprint |
| **Roon** | Cross-platform | Subscription | Premium discovery and streaming integration |
| **iTunes / Apple Music** | Cross-platform | Free/Sub | Mainstream; deep Apple ecosystem integration |
| **Plex** | Cross-platform | Freemium | Media server + remote streaming + client apps |
| **VLC** | Cross-platform | Free | Universal format support; disc + network streams |

---

### 3.2 Feature Comparison Matrix

#### Core Library Features

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Local file library | ✅ | ✅ | ✅ | ✅ | ✅ |
| SQLite backend | ✅ | ✅ | ✅ | Custom | Custom |
| Smart playlists | ✅ | ✅ | ✅ | via plugin | ✅ |
| Auto-scan (watch folders) | ✅ | ✅ | ✅ | via plugin | ✅ |
| Duplicate detection | ⚠️ | ✅ | ✅ | via plugin | ✅ |
| Album grid / artwork browser | ❌ | ✅ | ✅ | via skin | ✅ |
| Sortable column browser | ❌ | ✅ | ✅ | ✅ | ✅ |
| Batch tag editor | ❌ | ✅ | ✅ | ✅ | ❌ |
| Ratings + play counts | ✅ | ✅ | ✅ | ✅ | ✅ |
| Grouping/custom tags | ✅ | ✅ | ✅ | ✅ | ❌ |

#### Playback & Audio Quality

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Gapless playback | ⚠️ | ✅ | ✅ | ✅ | ✅ |
| Crossfade | ✅ | ✅ | ✅ | via plugin | ✅ |
| Equalizer | ✅ | ✅ | ✅ | via plugin | ❌ |
| ReplayGain (read) | ❌ | ✅ | ✅ | ✅ | ✅ |
| ReplayGain (write/scan) | ❌ | ✅ | ✅ | ✅ | ❌ |
| Output device selection | ❌ | ✅ | ✅ | ✅ | ✅ |
| WASAPI / ASIO | ❌ | ✅ | ✅ | ✅ | ✅ |
| Bit-perfect / exclusive mode | ❌ | ✅ | ❌ | ✅ | ✅ |
| DSP chain / plugins | ❌ | ✅ | via plugin | ✅ | ❌ |
| Playback rate control | ✅ | ✅ | ✅ | ✅ | ❌ |
| Sleep timer | ✅ | ✅ | ✅ | via plugin | ❌ |

#### CD & Disc Features

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| CD ripping | ✅ | ✅ | ✅ | via plugin | ❌ |
| AccurateRip verification | ✅ | ✅ | ✅ | ✅ | ❌ |
| CUETools DB | ✅ | ❌ | ❌ | via plugin | ❌ |
| CD playback | ✅ | ✅ | ✅ | ✅ | ❌ |
| DVD/VCD playback | ✅ | ❌ | ❌ | ❌ | ❌ |
| MusicBrainz metadata | ✅ | ✅ | ✅ | via plugin | ✅ |
| CUE sheet support | ❌ | ✅ | ✅ | ✅ | ❌ |
| Multi-format rip output | ✅ | ✅ | ✅ | via plugin | ❌ |

#### Metadata & Discovery

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Automatic artwork download | ✅ | ✅ | ✅ | via plugin | ✅ |
| MusicBrainz lookup | ✅ | ✅ | ✅ | via plugin | ✅ |
| TheAudioDB enrichment | ✅ | ❌ | ❌ | ❌ | ❌ |
| Lyrics (embedded) | ✅ | ✅ | ✅ | via plugin | ✅ |
| Lyrics (online / synced) | ✅ | ✅ | ❌ | via plugin | ✅ |
| Acoustic fingerprinting (AcoustID) | ❌ | ✅ | ✅ | via plugin | ✅ |
| Artist biography / info | ❌ | ✅ | ✅ | ❌ | ✅ |
| Radio / recommendations | ❌ | ❌ | ❌ | ❌ | ✅ |
| Last.fm scrobbling | ❌ | ✅ | ✅ | via plugin | ✅ |
| Podcast support | ❌ | ✅ | ❌ | ❌ | ❌ |

#### Device Sync & Connectivity

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| MTP/USB device sync | ❌ | ✅ | ✅ | ❌ | ❌ |
| DLNA/UPnP server | ❌ | ✅ | ✅ | ❌ | ✅ |
| DLNA/UPnP renderer | ❌ | ✅ | ✅ | ❌ | ✅ |
| Airplay output | ❌ | ❌ | ❌ | ❌ | ✅ |
| Local network remote | ❌ | ⚠️ | ✅ | ❌ | ✅ |
| Mobile companion app | ❌ | ❌ | ✅ | ❌ | ✅ |
| Streaming service integration | ❌ | ❌ | ❌ | ❌ | ✅ |
| YouTube / web download | ✅ | ❌ | ❌ | ❌ | ❌ |
| Internet radio | ❌ | ✅ | ✅ | via plugin | ❌ |

#### Video & Multimedia

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | VLC | Plex |
|---------|:---:|:---:|:---:|:---:|:---:|
| Local video playback | ✅ | ❌ | ✅ | ✅ | ✅ |
| DVD/Blu-ray playback | ✅ | ❌ | ❌ | ✅ | ⚠️ |
| Network streams (URL/IPTV) | ❌ | ❌ | ❌ | ✅ | ✅ |
| Resume position | ❌ | N/A | ✅ | ⚠️ | ✅ |
| Subtitle sync/delay | ❌ | N/A | ❌ | ✅ | ✅ |
| Subtitle search/download | ❌ | N/A | ❌ | ❌ | ✅ |
| Theater / 10-foot mode | ❌ | N/A | ❌ | ❌ | ✅ |
| Video catalog with artwork | ✅ | N/A | ✅ | ❌ | ✅ |

---

### 3.3 Where Sea Lyon Leads

These are genuine competitive advantages that no single competitor matches simultaneously:

1. **CUETools DB verification** — unique among GUI media managers; only foobar2000 (via plugin) comes close. Sea Lyon integrates this natively with no setup.
2. **Multi-provider metadata chain** — CTDB → MusicBrainz → TheAudioDB is more thorough than any competitor's default pipeline.
3. **DVD/VCD playback integrated with the library** — MusicBee and foobar2000 don't do video; MediaMonkey plays video but not discs; only VLC matches this and it has no library.
4. **YouTube integration with library import** — no desktop media manager competitor offers this out of the box.
5. **All-in-one scope** — ripping + library + playback + video + YouTube in one installable app, no plugins required.

---

### 3.4 Where Sea Lyon Lags

These gaps must be closed to reach parity with MusicBee/MediaMonkey:

| Gap | MusicBee has it | MediaMonkey has it | Priority |
|-----|:-----------:|:------------:|---------|
| ReplayGain read + scan | ✅ | ✅ | Critical |
| Output device / WASAPI selection | ✅ | ✅ | Critical |
| Batch tag editor | ✅ | ✅ | High |
| Album grid browser | ✅ | ✅ | High |
| Acoustic fingerprinting | ✅ | ✅ | High |
| Last.fm scrobbling | ✅ | ✅ | High |
| DLNA/UPnP server | ✅ | ✅ | Medium |
| Internet radio | ✅ | ✅ | Medium |
| CUE sheet support | ✅ | ✅ | Medium |
| MTP/USB sync | ✅ | ✅ | Medium |
| Artist bio / info panels | ✅ | ✅ | Medium |
| Video resume + subtitle delay | ✅ | ✅ | Medium |
| Mobile companion | ❌ | ✅ | Low |

---

## 4. Gap Analysis

### 4.1 Previously Identified Bugs — Status: All Resolved

A code review dated 2026-05-15 identified seven P0/P1 bugs. All have been fixed in subsequent commits and were **verified by reading the current source**. No stability blockers remain.

| # | File | Issue | Status |
|---|------|--------|--------|
| 1 | `cd_detect.py` | `libdiscid` DLL handle not retained | **Fixed** — `_DLL_DIRECTORY_HANDLES` list; `close_dll_handles()` in `closeEvent` |
| 2 | `youtube_view.py` | Search QThreads orphaned on rapid search | **Fixed** — new search blocked while one runs; `shutdown()` joins/terminates |
| 3 | `yt_download_dialog.py` | Dialog closes while download worker runs | **Fixed** — `closeEvent` cancels and ignores close until thread exits |
| 4 | `yt_downloader.py` | yt-dlp ImportError leaves dialog disabled | **Fixed** — both `error` + `download_finished` emitted; UI re-enables |
| 5 | `ripper.py` | libcdio cancel hangs on carriage-return progress | **Fixed** — 0.1s poll loop with drain thread; cancel checked every iteration |
| 6 | `ripper.py` | Partial ffmpeg output files not removed on cancel | **Fixed** — `_cleanup_partial()` called on all cancel/error exit paths |
| 7 | `build/lyon.spec` | ROOT variable pointed to wrong directory | **Fixed** — `SPEC_DIR` + `is_dir()` guard; `ROOT = SPEC_DIR.parent` is correct |

### 4.2 Feature Gaps by Priority

#### Critical — Blocks audiophile / power-user adoption
- **ReplayGain:** No loudness scan, read, or playback mode. Standard expectation for any music app targeting FLAC users.
- **Output device selection:** Cannot choose audio output device (WASAPI on Windows). Required for users with DACs or multiple outputs.
- **Batch metadata editor:** Cannot edit tags on more than one track at a time. Core workflow for library cleanup.

#### High — Required for MusicBee parity
- **Acoustic fingerprinting (AcoustID):** No "Identify by audio" workflow; duplicates detected by text only.
- **Album grid browser:** Library has list/simple mode but no artwork-forward grid view.
- **Last.fm / ListenBrainz scrobbling:** No play history submitted to external services.
- **Sortable column browser:** Cannot sort tracks by year, bitrate, duration, etc. in the library pane.
- **CUE sheet support:** No parsing or playback of `.cue` + image archives (common for ripped CDs).

#### Medium — Required for MediaMonkey parity
- **DLNA/UPnP server:** Cannot stream library to TVs, speakers, or other DLNA renderers.
- **Internet radio:** No Shoutcast/Icecast URL playback.
- **Video resume position:** No per-file last-position tracking.
- **Subtitle delay controls:** VLC supports it; Sea Lyon doesn't expose it.
- **Artist bio / info panel:** TheAudioDB has bios; they're fetched but not displayed anywhere.
- **MTP/USB sync:** Cannot sync to Android or portable DAPs.

#### Low — Nice-to-have / differentiation
- **Podcast support:** Not in scope but MusicBee users expect it.
- **Streaming service integration:** Out of scope for v1 but table-stakes for Roon comparison.
- **Mobile companion / remote:** Complex, but DLNA remote control would partially address this.
- **Network stream playback (URL/IPTV):** VLC can; Sea Lyon's video player cannot.
- **Theater / 10-foot mode:** Full-screen video mode with navigation designed for living room distance.

---

## 5. Implementation Plan

### Phase 0 — ~~Stabilization~~ Complete ✓
*All seven P0/P1 bugs from the 2026-05-15 code review have been resolved. The codebase is production-stable. Phase 1 work can begin immediately.*

| Item | Resolution |
|------|-----------|
| libdiscid DLL handle | `_DLL_DIRECTORY_HANDLES` + `close_dll_handles()` in shutdown |
| YouTube thread leaks | `shutdown()` method; new searches blocked while one runs |
| Download dialog race | `closeEvent` cancels worker and ignores close until thread exits |
| yt-dlp import error | `error` + `download_finished` both emitted; UI re-enables |
| Rip cancel hang | 0.1s poll loop with drain thread; `_cleanup_partial()` on exit |
| Partial file leak | `_cleanup_partial()` on all error and cancel paths |
| PyInstaller ROOT | `SPEC_DIR` + `is_dir()` guard; correct project root |

---

### Phase 1 — Audio Quality & Power User (v0.6)
*Estimated: 3–4 weeks*

**1.1 ReplayGain**
- Add `rgain3` or `loudnorm` via ffmpeg to requirements
- `lyon/core/replaygain.py`: scan tracks (album-mode or track-mode); write R128_TRACK_GAIN / REPLAYGAIN_TRACK_GAIN to tags via mutagen
- `lyon/core/player.py`: read ReplayGain tags on load; apply gain to VLC audio volume pre-output
- Settings: ReplayGain mode (off / track / album), pre-amp, clipping prevention
- Library view: batch "Scan ReplayGain" context menu action on album or selection

**1.2 Output Device Selection**
- `lyon/core/playback_backend.py`: expose VLC `--aout` and `--alsa-audio-device` / `--wasapi-audio-device` options
- `lyon/core/settings.py`: add `audio_output_device` key
- Settings dialog: populate device list via `libvlc_audio_output_device_enum()`; allow selection; restart player on change

**1.3 Batch Tag Editor**
- `lyon/ui/batch_tag_dialog.py`: multi-row selection → dialog showing common fields (artist, album artist, genre, year, album, grouping); fields left blank are skipped; "Apply to N tracks" button
- Wire to right-click context menu in library track list
- Use existing `tagger.py` write methods per track

**1.4 Gapless Playback**
- Verify VLC `--audio-time-stretch-enabled 0` and pre-buffering are set; test with split-track FLAC albums
- Add gapless mode toggle to settings

---

### Phase 2 — Library Parity with MusicBee (v0.7)
*Estimated: 4–6 weeks*

**2.1 Album Grid Browser**
- `lyon/ui/library_view.py`: add `QListView` with `QAbstractItemDelegate` that renders 180×180 artwork + album title + artist + year
- Load artwork from `library.get_cover_art()` with async pixmap cache (avoid blocking UI thread)
- Toggle button in toolbar (list / grid)
- Double-click grid item → show track list for that album

**2.2 Sortable Column Browser**
- Replace fixed-order `QListWidget` in track pane with `QTableView` + `QSortFilterProxyModel`
- Columns: #, Title, Artist, Album, Year, Duration, Bitrate, Rating
- Click column header to sort ascending/descending
- Persist column widths and sort order to settings

**2.3 Acoustic Fingerprinting (AcoustID)**
- Add `pyacoustid` + `chromaprint` to requirements (or call `fpcalc` binary)
- `lyon/core/fingerprint.py`: generate fingerprint for a file path; query AcoustID API → return list of `(score, mbid, title, artist)` candidates
- Library view context menu: "Identify Track" → fingerprint → show candidate dialog → apply metadata + MusicBrainz ID
- Duplicate detection: add hash + fingerprint match option in `duplicate_dialog.py`

**2.4 Last.fm / ListenBrainz Scrobbling**
- `lyon/core/scrobbler.py`: authenticate with Last.fm (API key + secret, OAuth flow) and/or ListenBrainz (user token)
- Hook into `player.py`'s play-count increment point; submit "Now Playing" on track start, "Scrobble" after 50% play or 4 minutes
- Settings: enable/disable per service; account login/logout button

**2.5 CUE Sheet Support**
- `lyon/core/cue_parser.py`: parse `.cue` + paired image file; split into virtual tracks with title, performer, and INDEX 01 offset
- Add `.cue` to library scan; store as virtual playlist in library
- Playback: seek to CUE offset within parent image file

**2.6 Enhanced Duplicate Detection**
- `lyon/core/fingerprint.py` (from 2.3): optional file MD5/SHA256 hash comparison
- `duplicate_dialog.py`: expose "match by hash" and "match by fingerprint" modes in addition to existing title+artist normalization

---

### Phase 3 — Discovery & Connectivity (v0.8)
*Estimated: 5–7 weeks*

**3.1 Internet Radio**
- `lyon/core/radio.py`: parse Shoutcast/Icecast m3u/pls/m3u8 streams; fetch station list from community-maintained source
- `lyon/ui/radio_view.py`: station browser with search, genre filter, favicon, bitrate
- Playback via existing player `play_url()` method (already takes a path; extend to URIs)
- Save favorite stations to library as a "Radio" playlist type

**3.2 DLNA / UPnP Server**
- Add `python-didl-lite` + `async-upnp-client` to requirements
- `lyon/core/dlna_server.py`: minimal MediaServer device; serve tracks from library with correct MIME types; announce via SSDP
- Settings: enable DLNA server, port, friendly name, allowed networks
- This enables streaming library to smart TVs, receivers, and phones without a companion app

**3.3 Artist Bio / Info Panel**
- `lyon/ui/artist_panel.py`: collapsible side panel in Now Playing showing artist photo, bio (from TheAudioDB), similar artists, and discography count
- TheAudioDB artist data already fetched in metadata pipeline; parse and cache it

**3.4 Video Resume Position**
- `library.py`: add `resume_position` column (integer seconds) and `last_played_video` to schema migration v8
- `video_player_view.py`: on stop/close, save current position; on load, seek to saved position with a "Resume from MM:SS?" toast

**3.5 Subtitle Delay Controls**
- `video_player_view.py`: expose `libvlc_video_set_spu_delay()` via a ±50ms step button and fine-tune slider in the video controls bar

**3.6 Network Stream Playback**
- Video player: add "Open URL" button; pass URL directly to VLC (already supports HTTP/RTSP/HLS)
- Add URL to recent streams list in settings

---

### Phase 4 — Platform & Ecosystem (v1.0)
*Estimated: 6–8 weeks*

**4.1 MTP / USB Device Sync**
- Add `pymtp` or `libmtp` binding; enumerate connected MTP devices
- `lyon/core/device_sync.py`: two-way sync with configurable rules (format transcode, quality cap, playlist export)
- `lyon/ui/device_view.py`: device browser tab; drag tracks to device; progress sync

**4.2 Cross-Platform CD Detection**
- `cd_detect.py`: add Linux (`/dev/cdrom`) and macOS (`/dev/disk*`) detection paths
- Remove Windows-only gating so the rest of the ripping pipeline works on all platforms

**4.3 Podcast Support**
- `lyon/core/podcast.py`: RSS feed parser; episode download; played position tracking
- Library sidebar section: Podcasts (separate from music)

**4.4 Full-Text Search Improvements**
- SQLite FTS5 virtual table over title, artist, album, genre, grouping
- Incremental search as user types (debounced 200 ms)
- Global search bar in main window toolbar that searches across all tabs

**4.5 Accessibility Audit**
- Set `setAccessibleName()` on all icon-only buttons (transport, toolbar)
- Replace emoji/symbolic text (>>>, M) with `QIcon`-based buttons + tooltips
- Keyboard navigation: Tab order through all controls, focus indicators visible

**4.6 macOS Sandboxed Distribution**
- Code signing + notarization for macOS `.dmg`
- Adapt Win32-specific paths in `cd_detect.py`, `media_keys.py` to be platform-conditional (many already are)

---

## 6. Development Roadmap

### Timeline Overview

```
2026          Q2            Q3            Q4
              May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
v0.5 ────────■
v0.6          ├── Phase 0 ──┤
               ├──── Phase 1 ────────────┤
v0.7                         ├──── Phase 2 ────────────┤
v0.8                                      ├──── Phase 3 ──────────────■
v1.0                                                    ├──── Phase 4 ────■
```

---

### Milestone Definitions

#### ~~v0.5.1 — Stability Release~~ — Skipped: all P0/P1 bugs resolved in v0.5.0 branch
*The seven blocking bugs from the code review were fixed within the LMM-DEV branch. No separate stability release is needed; ship v0.5.0 and move directly to v0.6.0 feature work.*
- [x] libdiscid DLL handle retention ✓
- [x] YouTube thread leaks (search + download) ✓
- [x] yt-dlp import error recovery ✓
- [x] Rip cancellation hang + partial file cleanup ✓
- [x] PyInstaller build spec ✓
- [ ] Regression test suite green on Windows *(still needed)*

#### v0.6.0 — Audio Quality Release (Target: August 2026)
*Phase 1 complete. Audiophile-grade playback.*
- [ ] ReplayGain scan, read, and playback
- [ ] Output device / WASAPI selection
- [ ] Batch tag editor
- [ ] Gapless playback verified

#### v0.7.0 — Library Parity Release (Target: October 2026)
*Phase 2 complete. MusicBee functional parity.*
- [ ] Album grid browser with async artwork loading
- [ ] Sortable column browser
- [ ] Acoustic fingerprinting (AcoustID identify + deduplication)
- [ ] Last.fm + ListenBrainz scrobbling
- [ ] CUE sheet support
- [ ] Enhanced duplicate detection (hash + fingerprint)
- [ ] All v0.6.0 items included

#### v0.8.0 — Discovery & Connectivity Release (Target: December 2026)
*Phase 3 complete. MediaMonkey connectivity parity.*
- [ ] Internet radio (Shoutcast/Icecast)
- [ ] DLNA/UPnP server
- [ ] Artist bio / info panel in Now Playing
- [ ] Video resume position
- [ ] Subtitle delay controls
- [ ] Network stream / URL playback
- [ ] All v0.7.0 items included

#### v1.0.0 — Platform Release (Target: Q1 2027)
*Phase 4 complete. Production-grade cross-platform release.*
- [ ] MTP/USB device sync
- [ ] Cross-platform CD detection (Linux, macOS)
- [ ] Podcast support
- [ ] Full-text search (FTS5)
- [ ] Accessibility audit complete
- [ ] macOS code-signed + notarized DMG
- [ ] All v0.8.0 items included

---

### Backlog (Post-v1.0 / Aspirational)

These items would move Sea Lyon from parity to leadership:

| Item | Strategic Value |
|------|----------------|
| **Streaming service integration** (Tidal, Qobuz) | Competes with Roon at fraction of cost |
| **Mobile companion app** (iOS/Android remote) | Full MediaMonkey + Roon remote parity |
| **AI-powered smart playlists** (mood, tempo, energy) | No current competitor does this well natively |
| **Automatic concert/event alerts** (Songkick/Bandsintown) | Discovery differentiator |
| **Integrated lyrics editor** | Write/sync LRC timestamps in-app |
| **Plugin / extension API** | foobar2000-style ecosystem; dramatically expands reach |
| **Cloud backup / sync of library metadata** | Cross-machine library; competes with iTunes Match concept |
| **Hi-res audio store integration** (7digital, HDtracks) | Purchase-to-library pipeline |
| **Podcast + audiobook unified library** | Single app for all audio content |
| **Linux Flatpak / AppImage packaging** | Opens Linux enthusiast market |

---

### Resource Estimates

These are single-developer estimates. Team size scales proportionally.

| Phase | Effort | Key Risk |
|-------|--------|----------|
| Phase 0 (Stability) | 3–5 days | Low — known fixes |
| Phase 1 (Audio Quality) | 3–4 weeks | Medium — VLC WASAPI binding quirks |
| Phase 2 (Library Parity) | 4–6 weeks | Medium — fingerprint binary distribution |
| Phase 3 (Connectivity) | 5–7 weeks | High — DLNA protocol complexity |
| Phase 4 (Platform) | 6–8 weeks | High — MTP + cross-platform CD |
| **Total to v1.0** | **~5–6 months** | |

---

### Key Technical Decisions Required Before v0.7

1. **Chromaprint distribution:** Ship `fpcalc.exe` in the installer or require users to install it. Shipping is simpler UX; installing is smaller package.
2. **DLNA vs. alternative:** `python-didl-lite` is pure Python but limited. Consider `MiniDLNA` or `Gerbera` as an optional sidecar process — simpler to maintain than implementing the full UPnP stack.
3. **Scrobbling OAuth flow:** Last.fm requires a browser-based OAuth redirect. A local HTTP server callback (similar to Spotify PKCE) is the cleanest approach without a backend.
4. **FTS5 migration:** Adding an FTS5 table to the existing schema requires a `CREATE VIRTUAL TABLE` migration. Plan this as schema version 8 ahead of v0.7 search improvements.
5. **Podcast storage:** Keep podcasts in the main library database (same `tracks` table with `source='podcast'`) or a separate SQLite file. Separate file is cleaner isolation; same file simplifies smart playlists.

---

*Report generated from codebase analysis of Sea Lyon Media Manager v0.5.0 (branch: LMM-DEV, commit 6f006c0). Analysis covers all files under `lyon/core/`, `lyon/ui/`, existing review docs in `docs/reviews/`, and competitive feature research as of 2026-05-17.*
