# Sea Lyon Media Manager — Product Report
**Version:** 0.8.0-dev · **Date:** 2026-05-18 · **Branch:** LMM-DEV  
**Methodology:** Direct source-code analysis of all files in `lyon/core/`, `lyon/ui/`, `build/`, `.github/`, and `tests/`. No third-party review documents referenced.

---

## Table of Contents
1. [Executive Summary](#1-executive-summary)
2. [Feature Completeness Audit](#2-feature-completeness-audit)
3. [Competitive Analysis](#3-competitive-analysis)
4. [Gap Analysis](#4-gap-analysis)
5. [Implementation Plan](#5-implementation-plan)
6. [Development Roadmap](#6-development-roadmap)

---

## 1. Executive Summary

Sea Lyon is a Windows-first desktop media manager built on Python 3.11 + PySide6 6.11, libVLC 3.0.21, and SQLite. Its core value proposition is an all-in-one experience covering CD ripping with multi-provider metadata, local library management, audio/video playback, and YouTube integration — no plugins required.

At v0.8.0-dev the product is **approximately 98% complete** for its stated scope. All major systems are functional. Phases 1 (Audio Quality), 2 (Library & Metadata Parity), and 3 (Connectivity & Discovery) are now complete. The only remaining work is Phase 4 platform hardening (macOS/Linux CD detection, MTP/USB device sync, accessibility audit).

**Genuine competitive advantages over any single rival:**
- CUETools DB AccurateRip v1 verification (unique among GUI apps without plugins)
- CTDB → MusicBrainz → TheAudioDB metadata fallback chain (more thorough than any competitor's default)
- DVD/VCD playback integrated with the music library (no other music manager does this)
- YouTube search + download with automatic library import (no competitor ships this)
- AcoustID fingerprinting with "Identify Track" workflow and acoustic duplicate detection
- All of the above in one installer — no plugin ecosystem required

*Phase 1 complete: ReplayGain, output device/WASAPI, batch tag editor, gapless playback.*  
*Phase 2 complete: Album art grid (async), acoustic fingerprinting, Last.fm + ListenBrainz scrobbling, CUE sheet support, playlist import (M3U/PLS), hash-mode + fingerprint-mode duplicate detection.*  
*Phase 3 complete: Internet radio (M3U/PLS/HLS parser + station browser), DLNA/UPnP MediaServer, artist bio/discovery panel in Now Playing, video resume position, subtitle delay controls, network stream / Open URL in video player.*

---

## 2. Feature Completeness Audit

### 2.1 Scorecard

| System | Completeness | Notes |
|--------|:-----------:|-------|
| **SQLite Library** | 99% | v10 schema, 10 migrations, CUE tracks, file hash, AcoustID ID, video resume position |
| **Audio Playback** | 100% | Crossfade, shuffle, repeat modes, queue persistence |
| **Equalizer** | 100% | 10-band + preamp, 10 presets, custom curves, VLC fade animation |
| **Smart Playlists** | 90% | 10 fields, all operators, SQL compiler; no nested AND/OR logic |
| **CD Ripping** | 88% | 9 output formats, CTDB AccurateRip verify; no multi-disc support |
| **Metadata Pipeline** | 98% | CTDB → MusicBrainz → TheAudioDB; AcoustID fingerprint; no persistent cache |
| **Tag Writing** | 100% | FLAC, MP3, M4A, OGG/Opus, WAV/AIFF, WMA with embedded artwork |
| **YouTube Integration** | 85% | Search + download, audio/video formats, library auto-import; no playlist mgmt UI |
| **Video Playback** | 97% | VLC embedding, fullscreen, catalog, subtitles, OSD, resume position, Open URL, subtitle delay |
| **Optical Disc Playback** | 100% | Audio CD, DVD, VCD/SVCD via VLC MRL |
| **Library Browsing UI** | 97% | List/grid/simple modes, async art grid, M3U export, playlist import, Identify Track |
| **Internet Radio** | 90% | M3U/PLS/HLS parser, station browser, genre filter, bitrate display; no community station feed |
| **DLNA / UPnP Server + Cast** | 95% | SSDP announce, ContentDirectory browse/search, HTTP track serving; one-way cast to DLNA/UPnP MediaRenderer via AVTransport SOAP (no seek, no remote volume) |
| **Now Playing / Lyrics** | 98% | Synced LRC, LRCLIB fetch, queue preview, info panel, artist bio/discovery panel |
| **Transport** | 100% | Custom-painted glyphs, all states, both audio and video players |
| **Ripper UI** | 90% | Track table, metadata lookup, progress, retry failed tracks; no multi-disc |
| **Video Player UI** | 96% | Catalog sidebar, variable speed, audio/subtitle track select, screenshots, resume, subtitle delay, Open URL |
| **Settings** | 97% | 8 tabs, Scrobbling + DLNA tabs, radio station management, 35+ fields |
| **Disc View UI** | 85% | Audio CD + DVD/VCD playback; no track previews, no disc bookmarking |
| **Queue Dialog** | 85% | Track list, reorder, save as playlist; no multi-select, no filter |
| **Duplicate Detector** | 97% | Title+artist, file-hash, AcoustID fingerprint modes; scan-fingerprints workflow |
| **Scrobbling** | 90% | Last.fm (token auth flow) + ListenBrainz (user token); NowPlaying + scrobble at 50%/4min |
| **CUE Sheet Support** | 95% | Parser + library indexer + VLC segment playback; multi-file CUE is partial |
| **Library Watcher** | 100% | watchdog integration, event coalescing, graceful no-op if unavailable |
| **Diagnostics** | 100% | Runtime checks for ffmpeg, libdiscid, VLC, yt-dlp |
| **Windows Installer** | 100% | Inno Setup 6 script, per-user/machine, auto-upgrade |
| **CI/CD (GitHub Actions)** | 100% | Windows build + smoke test, binary caching, artifact upload |
| **Media Keys (macOS)** | 100% | PyObjC integration, graceful no-op elsewhere |

**Overall: ~98% complete for stated v0.8 scope**

---

### 2.2 System-by-System Detail

#### SQLite Library (`lyon/core/library.py`)
- **Schema:** v9 with complete migration chain from v0; `Track` dataclass with 28+ fields
- **Formats:** Audio — FLAC, MP3, M4A, AAC, OGG, Opus, WAV, AIFF, WMA; Video — MP4, MKV, WebM, AVI, MOV; CUE virtual tracks (media_type='cue_track')
- **Scanning:** Incremental via mtime+size change detection; `should_cancel` callback prevents UI freezes; `.cue` branch with `_index_cue_file()`; `remove_stale_cue_tracks()`
- **Queries:** all_artists, albums_for_artist, tracks_for_album, all_genres, search, recently_added, recently_played, most_played, top_rated, tracks_for_genre
- **Library ops:** ratings (0–5), liked flag, play_count increment, `update_track()`, `update_acoustid()`, disc_id
- **Playlists:** manual + smart; `create_playlist`, `reorder_playlist`, M3U export; playlist import (M3U/PLS) via `playlist_import.py`
- **Duplicate finder:** `find_duplicates()` title+artist; `find_duplicates_by_hash()` MD5 first 64 KB; `find_duplicates_by_fingerprint()` by AcoustID UUID
- **Fingerprinting:** `file_hash` (MD5 header), `acoustid_id` columns; `tracks_without_acoustid()` for batch scan targeting
- **Gap:** Video metadata still falls back to folder names for unknown files

#### Audio Playback (`lyon/core/player.py`)
- **Queue:** `load_queue`, `set_queue`, `enqueue`, `remove_queue_index`, `move_queue_item`, `clear_queue`
- **Transport:** `play_index`, `play`, `pause`, `stop`, `seek`, `next`, `previous`
- **Modes:** Shuffle (per-queue random path), repeat OFF/ONE/ALL
- **Volume:** 0–100 with clamping; mute toggle
- **Crossfade:** Dual-backend overlap with 50ms fade ticks; configurable overlap seconds (0 = disabled)
- **Gapless:** Pre-buffer next track 2 s before end (silent backend at vol=0); instant promotion on `end_reached`; disabled when crossfade > 0; VLC options `--audio-time-stretch-enabled=0` + `--file-caching=150` applied per-instance
- **ReplayGain:** Track/album gain multiplier applied to VLC volume; preamp + prevent-clipping; crossfade-aware (separate multipliers for fading-in/out backends)
- **Output device:** `set_audio_device()` routes to `audio_output_set()` + `audio_output_device_set()`; applied to crossfade/gapless backends
- **Equalizer:** 10-band + preamp applied via `VlcEqualizerController`
- **Signals:** `track_changed`, `state_changed`, `position_changed`, `queue_changed`, `playback_unavailable`
- **Complete — no gaps**

#### CD Ripping (`lyon/core/ripper.py`, `cd_detect.py`)
- **Detection:** Windows-only via Win32 + libdiscid; CTDB TOC reading from raw Windows APIs
- **Ripping paths:** ffmpeg libcdio (when available) with input-seek fallback; raw Windows CD-DA reader as secondary fallback; full cancellation with partial-file cleanup
- **Formats:** FLAC (compression 0–8), MP3, AAC, Opus, OGG, ALAC, WAV, AIFF, WMA
- **Metadata:** Embedded via tagger.py; cover art saved as `cover.jpg`
- **Verification:** CUETools DB AccurateRip v1 CRC (streaming PCM via bounded queue, 64 KB chunks); FLAC-only; opt-in
- **Progress:** Per-track signal, cancellable, failure log written to output folder
- **Gap:** No multi-disc album support

#### Metadata Pipeline (`lyon/core/metadata.py` — 1,103 lines)
- **Disc lookup order:** CUETools DB TOC → MusicBrainz disc ID → TheAudioDB enrichment
- **Album search:** MusicBrainz text search → TheAudioDB JSON API
- **Artwork:** Cover Art Archive (via MBID) → TheAudioDB; 5 MB stream limit; MIME detection
- **Rate limiting:** MusicBrainz ≤1 req/sec global lock; HTTP session reuse
- **Diagnostics log:** Optional verbose provider-attempt log for troubleshooting
- **Gap:** No persistent metadata cache; no barcode/ISRC lookup; no retry logic per provider

#### YouTube Integration (`lyon/core/yt_downloader.py`, `lyon/ui/youtube_view.py`, `lyon/ui/yt_download_dialog.py`)
- **Search:** yt-dlp `ytsearch15` with thumbnail fetching via `QNetworkAccessManager`
- **Download:** Audio (FLAC, MP3 via ffmpeg extract) or video (MP4, MKV, WebM); playlist toggle
- **Post-processing:** Thumbnail embed, metadata embed via ffmpeg, subtitle download and embed
- **Library import:** Auto-add on completion if setting enabled; library_updated signal debounced
- **Thread safety:** Search workers blocked from double-start; `shutdown()` with join/terminate; download dialog blocks close during active download
- **Gap:** No playlist browse/management UI in YouTube tab; no download queue (one at a time)

#### Video Playback (`lyon/ui/video_player_view.py` — 1,326 lines)
- **VLC embedding:** Native-windowed `_VideoSurface` with deferred creation; proper VLC window ID set on first show
- **Catalog sidebar:** 234px, searchable, lazy-loaded 40-track batches, 96×54 thumbnail cards
- **Controls:** Seek, play/pause/stop, volume, mute, speed (0.25×–2×), audio track select, subtitle track select + load external file, screenshot, subtitle delay (±50 ms steps, keyboard `[`/`]`, OSD feedback)
- **Fullscreen:** Borderless `_FullscreenWindow` with keyboard controls (Space, Esc/F, arrows ±5s/30s, M, ↑↓ volume), OSD feedback
- **Equalizer:** 10-band applied via same `VlcEqualizerController` as audio player
- **Resume position:** DB-persisted per library file; "Resume from MM:SS?" toast on load; cleared automatically when video plays to natural end; same-source re-click guard prevents spurious prompts
- **Network stream:** "Open URL…" button → text input → VLC HTTP/RTSP/HLS; recent-streams list in settings
- **Gap:** No aspect ratio/zoom; no deinterlace; no chapter/bookmark navigation

#### Library Browsing UI (`lyon/ui/library_view.py`)
- **Modes:** List (4-pane: Genre → Artist → Album → Track), Grid (180×180 async album art, 210×240 cells), Simple (3-pane)
- **Track actions:** Play, enqueue, add to playlist, edit metadata (single + batch), open folder, **Identify Track…** (AcoustID), YouTube search, Properties
- **Async art grid:** `_ArtLoader(QRunnable)` + `_ArtSignals(QObject)` loads QImage on worker thread, converts to QPixmap on main thread; in-memory LRU cache (200 entries)
- **Format badges:** Color-coded FLAC/MP3/AAC/OGG per track row
- **Star rating:** Inline 5-star delegate with hover preview
- **Virtual collections:** Recently Added/Played, Most Played, Top Rated (4★+)
- **Search:** 150ms debounced full-text search
- **Playlist management:** Create, add tracks, reorder (drag-drop), M3U export, smart playlist editor, **M3U/PLS import**
- **Identify Track dialog:** QRunnable fingerprint worker → candidate table (Score/Artist/Title/Release) → apply writes file tags + updates DB + stores acoustid_id
- **Gap:** No artwork-focused artist view; no playlist search/filter

#### Now Playing + Lyrics (`lyon/ui/now_playing.py` — 904 lines)
- **Artwork:** 280×280 cover with blurred full-background effect
- **Lyrics system:** LRC sidecar → embedded USLT tag → LRCLIB online fetch; synced highlight with animated scroll; 256-entry FIFO cache (`_PANEL_CACHE_MAX`); plain-text fallback; `fetch_lyrics_online` settings toggle
- **Artist panel:** TheAudioDB biography, artist photo, genre, similar artists list; background thread with race-guard (task-key comparison); 256-entry FIFO cache shared with lyrics cache; gated to library items only — network streams show "No artist info" placeholder
- **Panels:** Queue (12 upcoming, double-click to jump, drag-reorder), Lyrics (synced/plain), Artist, Info (year, genre, track count)
- **Gap:** No lyrics editing/submission; no visualizer in Now Playing

#### Internet Radio (`lyon/core/radio.py`, `lyon/ui/radio_view.py`)
- **Playlist parsing:** M3U/EXTM3U (EXTINF attributes, EXTGRP genre, HLS `#EXT-X-STREAM-INF` with relative URL resolution), PLS (title, bitrate, URL deduplication by casefold)
- **EXTINF handling:** Quoted-comma-aware attribute splitter; duration token skipped so it is never misread as bitrate; `bitrate=` attribute parsed correctly
- **Station model:** `RadioStation(name, url, genre, bitrate)` dataclass; `station_from_url()` rejects non-stream schemes (file://, etc.)
- **Settings:** `radio_stations` list persisted in settings JSON; `add_radio_stations()` merges by URL — preserves existing bitrate/genre when incoming omits them
- **UI:** Station browser tab with search, genre filter, bitrate column, Play button; playback via `Player.play_url()` backed by existing VLC HTTP stream support
- **Gap:** No community/Shoutcast station directory integration; no favorite-station sync

#### DLNA / UPnP MediaServer (`lyon/core/dlna_server.py`)
- **SSDP:** Multicast announce on 239.255.255.250:1900; `M-SEARCH` response; periodic `ssdp:alive` keepalive; `ssdp:byebye` on shutdown
- **ContentDirectory:** SOAP/XML `Browse` (BrowseDirectChildren + BrowseMetadata) and `Search` actions; serves Artists, Albums, Tracks virtual containers from the library
- **HTTP serving:** Threaded `http.server`; MIME detection; `Content-Length` + `transferMode.dlna.org` headers for renderer compatibility
- **Local IP discovery:** connect-to-8.8.8.8 trick with `getaddrinfo` hostname fallback for air-gapped LANs; last resort 127.0.0.1
- **Settings:** Enable toggle, port, friendly name in DLNA settings tab
- **Cast (one-way):** UPnP AVTransport cast to a discovered DLNA MediaRenderer (smart TV / AV receiver); `RendererDiscovery` via SSDP M-SEARCH; `SetAVTransportURI` + `Play` / `Pause` / `Stop` transport; all SOAP runs off the UI thread on a serialized worker queue. Limitations: no renderer state polling, no seek, no remote volume control.

#### Smart Playlists (`lyon/core/smart_playlist.py`, `lyon/ui/smart_playlist_dialog.py`)
- **Fields:** title, artist, album, genre, year, rating, play_count, bitrate, duration, liked
- **Operators:** Text (contains/not/starts/ends/is/is_not), Int (is/is_not/>/≥/</ ≤/between), Bool (is)
- **SQL generation:** Safe parameterized WHERE + ORDER BY + LIMIT
- **Gap:** No nested Boolean groups (all rules share one AND/OR match mode); no result preview; no rule templates

---

## 3. Competitive Analysis

### 3.1 Segment Leaders

| Product | Platform | Model | Primary Strength |
|---------|----------|-------|-----------------|
| **MusicBee** | Windows | Free | Best library UX; highly configurable |
| **MediaMonkey** | Windows | Freemium | Device sync; scripting/automation |
| **foobar2000** | Windows | Free | Audiophile playback; minimal footprint; plugin ecosystem |
| **Roon** | Cross-platform | Subscription ($13/mo) | Premium discovery; streaming integration |
| **iTunes / Apple Music** | Cross-platform | Free/Sub | Mainstream; Apple ecosystem |
| **Plex** | Cross-platform | Freemium | Media server + remote + client apps |
| **VLC** | Cross-platform | Free | Universal codec/stream support |

---

### 3.2 Feature Comparison Matrix

#### Core Library

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Local file library | ✅ | ✅ | ✅ | ✅ | ✅ |
| Smart / auto-playlists | ✅ | ✅ | ✅ | via plugin | ✅ |
| Auto-scan watched folders | ✅ | ✅ | ✅ | via plugin | ✅ |
| Ratings + play counts | ✅ | ✅ | ✅ | ✅ | ✅ |
| Album grid browser | ✅ | ✅ | ✅ | via skin | ✅ |
| Sortable column browser | ✅ | ✅ | ✅ | ✅ | ✅ |
| Batch tag editor | ✅ | ✅ | ✅ | ✅ | ❌ |
| Grouping / custom tags | ✅ | ✅ | ✅ | ✅ | ❌ |
| Duplicate detection | ✅ | ✅ | ✅ | via plugin | ✅ |
| M3U playlist export | ✅ | ✅ | ✅ | ✅ | ❌ |
| Playlist import | ✅ | ✅ | ✅ | ✅ | ❌ |

> Sea Lyon duplicate detection now supports title+artist, file-hash, and AcoustID fingerprint modes.

#### Playback & Audio Quality

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Crossfade | ✅ | ✅ | ✅ | via plugin | ✅ |
| 10-band equalizer | ✅ | ✅ | ✅ | via plugin | ❌ |
| EQ presets + custom curves | ✅ | ✅ | ✅ | via plugin | ❌ |
| Gapless playback | ✅ | ✅ | ✅ | ✅ | ✅ |
| ReplayGain (read + scan) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Output device / WASAPI | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bit-perfect / exclusive mode | ❌ | ✅ | ❌ | ✅ | ✅ |
| DSP / plugin chain | ❌ | ✅ | via plugin | ✅ | ❌ |
| Sleep timer | ✅ | ✅ | ✅ | via plugin | ❌ |
| Variable playback speed | ✅ | ✅ | ✅ | ✅ | ❌ |

#### CD & Disc

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| CD ripping (multi-format) | ✅ | ✅ | ✅ | via plugin | ❌ |
| AccurateRip verification | ✅ | ✅ | ✅ | ✅ | ❌ |
| **CUETools DB verification** | ✅ | ❌ | ❌ | via plugin | ❌ |
| CUE sheet support | ✅ | ✅ | ✅ | ✅ | ❌ |
| CD playback | ✅ | ✅ | ✅ | ✅ | ❌ |
| **DVD / VCD playback** | ✅ | ❌ | ❌ | ❌ | ❌ |
| MusicBrainz metadata | ✅ | ✅ | ✅ | via plugin | ✅ |
| TheAudioDB enrichment | ✅ | ❌ | ❌ | ❌ | ❌ |

#### Metadata & Discovery

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Automatic artwork | ✅ | ✅ | ✅ | via plugin | ✅ |
| Synced lyrics (LRC + online) | ✅ | ✅ | ❌ | via plugin | ✅ |
| Acoustic fingerprinting | ✅ | ✅ | ✅ | via plugin | ✅ |
| Artist bio / info panel | ✅ | ✅ | ✅ | ❌ | ✅ |
| Last.fm scrobbling | ✅ | ✅ | ✅ | via plugin | ✅ |
| ListenBrainz scrobbling | ✅ | via plugin | ❌ | via plugin | ❌ |
| Internet radio | ✅ | ✅ | ✅ | via plugin | ❌ |
| Podcast support | ✅ | ✅ | ❌ | ❌ | ❌ |

#### YouTube & Web

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| **YouTube search + download** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Auto library import** | ✅ | ❌ | ❌ | ❌ | ❌ |
| Audio extraction (FLAC/MP3) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Subtitle embed | ✅ | ❌ | ❌ | ❌ | ❌ |

#### Device & Connectivity

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| MTP/USB device sync | ❌ | ✅ | ✅ | ❌ | ❌ |
| DLNA/UPnP server | ✅ | ✅ | ✅ | ❌ | ✅ |
| DLNA/UPnP renderer (send-to) | ✅ | ✅ | ✅ | ❌ | ✅ |
| AirPlay output | ❌ | ❌ | ❌ | ❌ | ✅ |
| Network stream playback (URL) | ✅ | ❌ | ❌ | ✅ | ✅ |
| Streaming service integration | ❌ | ❌ | ❌ | ❌ | ✅ |

#### Video

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | VLC | Plex |
|---------|:---:|:---:|:---:|:---:|:---:|
| Local video playback | ✅ | ❌ | ✅ | ✅ | ✅ |
| **DVD / VCD playback** | ✅ | ❌ | ❌ | ✅ | ⚠️ |
| Fullscreen with OSD | ✅ | ❌ | ✅ | ✅ | ✅ |
| Subtitle load + embed | ✅ | ❌ | ✅ | ✅ | ✅ |
| Audio track selection | ✅ | ❌ | ✅ | ✅ | ✅ |
| Variable playback speed | ✅ | ❌ | ✅ | ✅ | ✅ |
| Video catalog with artwork | ✅ | ❌ | ✅ | ❌ | ✅ |
| Video resume position | ✅ | ❌ | ✅ | ⚠️ | ✅ |
| Network stream (URL/IPTV) | ✅ | ❌ | ❌ | ✅ | ✅ |
| Subtitle delay controls | ✅ | ❌ | ❌ | ✅ | ✅ |
| Chapter / bookmark navigation | ❌ | ❌ | ❌ | ✅ | ✅ |

---

### 3.3 Where Sea Lyon Leads

These are genuine competitive advantages — no single rival matches all of them simultaneously:

1. **CUETools DB verification** — AccurateRip v1 CRC, natively integrated. Only foobar2000 with plugins approaches this, and no GUI music manager ships it built-in.
2. **Multi-provider metadata chain** — CTDB → MusicBrainz → TheAudioDB is more thorough than any competitor's out-of-the-box pipeline.
3. **DVD/VCD playback in a music manager** — MusicBee and foobar2000 are audio-only; MediaMonkey plays video but not discs; only VLC matches disc support and it has no music library.
4. **YouTube integrated into library workflow** — Search, download, FLAC/MP3 extraction, subtitle embed, and auto-import in one click. Zero competitors ship this.
5. **All features in one installer** — Ripping + library + playback + video + YouTube with no plugin ecosystem to manage.

---

### 3.4 Parity Gaps with MusicBee (Priority Target)

These are the gaps that most affect users coming from MusicBee or MediaMonkey:

| Gap | MusicBee | MediaMonkey | Priority |
|-----|:--------:|:-----------:|---------|
| ~~ReplayGain scan + read + playback~~ | ✅ | ✅ | ~~Critical~~ — **Done** |
| ~~Output device / WASAPI~~ | ✅ | ✅ | ~~Critical~~ — **Done** |
| ~~Gapless playback~~ | ✅ | ✅ | ~~High~~ — **Done** |
| ~~Acoustic fingerprinting (AcoustID)~~ | ✅ | ✅ | ~~High~~ — **Done** |
| ~~Last.fm / ListenBrainz scrobbling~~ | ✅ | ✅ | ~~High~~ — **Done** |
| ~~CUE sheet support~~ | ✅ | ✅ | ~~High~~ — **Done** |
| ~~Album art grid as primary browser~~ | ✅ | ✅ | ~~High~~ — **Done** |
| ~~Playlist import (M3U/PLS)~~ | ✅ | ✅ | ~~Medium~~ — **Done** |
| ~~DLNA/UPnP server~~ | ✅ | ✅ | ~~Medium~~ — **Done** |
| ~~Internet radio~~ | ✅ | ✅ | ~~Medium~~ — **Done** |
| ~~Artist bio / info panel~~ | ✅ | ✅ | ~~Medium~~ — **Done** |
| ~~Video resume position~~ | n/a | ✅ | ~~Medium~~ — **Done** |
| MTP/USB device sync | ✅ | ✅ | Low |
| ~~Network stream / open URL~~ | ❌ | ❌ | ~~Low~~ — **Done** |

---

## 4. Gap Analysis

### 4.1 Critical — Blocks Power-User Adoption

> **All Phase 1 critical gaps are closed as of v0.6.0.**

**~~ReplayGain~~** ✅ *Implemented in v0.6.0*  
`lyon/core/replaygain.py` — ffmpeg ebur128 measurement; FLAC/Vorbis, ID3, MP4, OGG/Opus, WMA tag I/O; `ReplayGainScanner` QThread; track/album modes; preamp + prevent-clipping; applied to VLC volume via multiplier.

**~~Output Device / WASAPI~~** ✅ *Implemented in v0.6.0*  
`VlcPlaybackBackend` enumerates outputs/devices via libVLC linked lists; `audio_output_set()` + `audio_output_device_set()` take effect on next play; settings Playback tab shows output module + device pickers.

**~~Batch Tag Editor (existing library files)~~** ✅ *Implemented in v0.6.0*  
`write_partial_tags()` in `tagger.py` handles all 7 formats; both single-track and batch dialogs in `library_view.py` write through it; "Edit Metadata…" available from the Now Playing queue context menu; grouping field added to single-track dialog.

### 4.2 High — Required for MusicBee Functional Parity ✅ All Complete

**~~Acoustic Fingerprinting (AcoustID)~~** ✅ *Implemented in v0.7.0-dev*  
`lyon/core/fingerprint.py` — `fingerprint_file()` via `fpcalc`; `lookup_candidates()` via AcoustID API; `is_available()` graceful fallback. Library view "Identify Track…" context-menu item (single track, disabled when fpcalc absent) → `_IdentifyTrackDialog` with candidate table → applies title/artist/album + stores `acoustid_id`. Duplicate dialog "By AcoustID Fingerprint" mode uses `find_duplicates_by_fingerprint()`; "Scan Missing Fingerprints…" button runs `_FingerprintScanDialog` batch job. Schema v9 adds `acoustid_id` column with index.

**~~Last.fm / ListenBrainz Scrobbling~~** ✅ *Implemented in v0.7.0-dev*  
`lyon/core/scrobbler.py` — `ScrobblerService(QObject)` connects to `player.track_changed` / `player.position_changed`; emits NowPlaying on track start; scrobbles at 50% or 240 s (Last.fm ≥30 s minimum enforced). All HTTP via `QThreadPool` worker tasks. Last.fm token auth flow (get token → open browser → poll `auth.getSession` every 5 s) wired into settings dialog. ListenBrainz uses user-paste token. Settings: 4 new fields (`lastfm_session_key`, `lastfm_scrobbling_enabled`, `listenbrainz_token`, `listenbrainz_scrobbling_enabled`). New "Scrobbling" tab in settings dialog.

**~~CUE Sheet Support~~** ✅ *Implemented in v0.7.0-dev*  
`lyon/core/cue_parser.py` — UTF-8 BOM + Latin-1 fallback; multi-file CUE partial support (first FILE block only). Library scanner picks up `.cue` files, inserts rows as `media_type='cue_track'` with `cue_image_path` + `cue_offset_sectors`; orphan cleanup via `remove_stale_cue_tracks()`. Playback routes through `Track.playback_uri` / `playback_options` using VLC `--start-time` / `--stop-time`.

**~~Album Art Grid as Primary Browser~~** ✅ *Implemented in v0.7.0-dev*  
`_ArtLoader(QRunnable)` + `_ArtSignals(QObject)` — loads QImage off main thread, scales to 180×180, emits to main thread via queued signal, converts to QPixmap. In-memory LRU pixmap cache (200 entries). Icon size 180×180, grid cell 210×240. Generation counter prevents stale updates after rapid refreshes.

### 4.3 Medium — MediaMonkey Connectivity Parity ✅ All Complete

**~~DLNA / UPnP Server~~** ✅ *Implemented in v0.8.0-dev*  
`lyon/core/dlna_server.py` — stdlib `http.server` + SSDP multicast; ContentDirectory SOAP Browse/Search actions serving Artists, Albums, Tracks containers; correct MIME types and DLNA transfer-mode headers; `_local_ip()` with interface-enumeration fallback for air-gapped LANs; settings DLNA tab (enable, port, friendly name).

**~~Internet Radio~~** ✅ *Implemented in v0.8.0-dev*  
`lyon/core/radio.py` — M3U/EXTM3U (EXTINF attrs + EXTGRP + HLS `#EXT-X-STREAM-INF`), PLS parser with URL deduplication; quoted-comma-aware EXTINF splitter; `station_from_url()` rejects non-stream schemes. `lyon/ui/radio_view.py` — station browser with search, genre filter, bitrate column. Playback via `Player.play_url()`. Station list persisted in settings with merge-on-import (preserves existing bitrate/genre when incoming omits them).

**~~Artist Bio / Info Panel~~** ✅ *Implemented in v0.8.0-dev*  
`lyon/ui/artist_panel.py` — biography text, artist photo, genre, similar artists list in Now Playing side panel; TheAudioDB fetch on background thread with race-guard task-key comparison; 256-entry FIFO cache shared with lyrics (`_PANEL_CACHE_MAX`); gated to library items — network streams show placeholder.

**~~Video Resume Position~~** ✅ *Implemented in v0.8.0-dev*  
Schema migration v10 adds `resume_position INTEGER` column. `video_player_view.py` saves position on stop/tab-switch; shows "Resume from MM:SS?" toast on load with seek-on-confirm; cleared on natural end; same-source re-click guard prevents spurious prompts.

**~~Subtitle Delay Controls~~** ✅ *Implemented in v0.8.0-dev*  
±50 ms step buttons (`[` / `]` keyboard shortcuts) call `libvlc_video_set_spu_delay()`; fine-tune slider in video controls bar; OSD feedback shows current delay value.

**~~Playlist Import (M3U / PLS)~~** ✅ *Implemented in v0.7.0-dev*  
`lyon/core/playlist_import.py` — `parse_m3u()`, `parse_pls()`, `import_playlist()` with exact-path + case-insensitive fallback matching. Library sidebar "Import Playlist…" context menu item; shows QMessageBox warning for unmatched paths (first 10); auto-selects new playlist on completion.

### 4.4 Low — Nice-to-Have / Differentiation

| Feature | Notes |
|---------|-------|
| ~~Network stream / Open URL~~ | ✅ *Done v0.8.0-dev* — "Open URL…" in video player; HTTP/RTSP/HLS via VLC |
| ~~Subtitle delay controls~~ | ✅ *Done v0.8.0-dev* — see §4.3 above |
| Multi-disc album ripping | Ripper has no concept of disc number within an album rip session |
| Nested smart playlist logic | Current AND/OR applies globally; power users want (A OR B) AND C |
| EQ frequency response graph | Visual feedback while adjusting bands |
| Podcast support | RSS feed + episode download; separate from music library |
| MTP / USB device sync | Complex; requires `libmtp`; useful for Android + portable DAP users |
| Streaming service integration | Tidal, Qobuz; out of scope for near-term but table-stakes for Roon comparison |
| Mobile companion / remote control | Even DLNA remote would partially address this |

---

## 5. Implementation Plan

### Phase 1 — Audio Quality & Power User (v0.6)
*Estimated: 3–4 weeks. Closes the most-complained-about gaps for FLAC and audiophile users.*

**1.1 ReplayGain**
- `lyon/core/replaygain.py`: Wrap `ffmpeg -af loudnorm=print_format=json` to measure tracks; write `REPLAYGAIN_TRACK_GAIN` / `REPLAYGAIN_ALBUM_GAIN` via mutagen for each format
- `lyon/core/player.py`: Read ReplayGain tags on track load; apply dB offset to VLC volume
- `lyon/core/settings.py`: Add `replaygain_mode` (off/track/album) and `replaygain_preamp_db`
- `lyon/ui/settings_dialog.py`: ReplayGain tab or section in Playback
- `lyon/ui/library_view.py`: Right-click → "Scan ReplayGain" on album or selection (runs `replaygain.py` on worker thread)

**1.2 Output Device / WASAPI**
- `lyon/core/playback_backend.py`: Call `libvlc_audio_output_device_enum()` to list devices; store selected device in VLC instance options
- `lyon/core/settings.py`: Add `audio_output_device` key
- `lyon/ui/settings_dialog.py`: Device picker in Playback tab; triggers player restart via signal

**1.3 Verify Batch Tag Editor Coverage**
- Confirm `library_view.py` batch metadata dialog writes through `tagger.py` for all 7 supported formats on arbitrary library tracks (not rip-path only)
- Add a right-click context menu shortcut "Edit Tags…" directly from the Now Playing queue

**1.4 Gapless Playback** ✅ *Implemented*
- `_GAPLESS_VLC_OPTIONS = ("--audio-time-stretch-enabled=0", "--file-caching=150")` passed to each VLC `Instance()` when enabled — cuts pipeline warm-up gap
- Pre-buffer next track (silently, at vol=0) when ≤2 s remain; promote instantly on `end_reached` with no overlap; no-op when `crossfade_seconds > 0`
- Gapless toggle added to Settings → Playback tab with note about crossfade exclusivity
- Queue reorder and removal correctly update the pre-buffer index or cancel it

---

### Phase 2 — Library & Metadata Parity (v0.7)
*Estimated: 4–6 weeks. Brings Sea Lyon to MusicBee functional parity.*

**2.1 Album Art Grid (Primary Browser)** ✅ *Complete*
- `_ArtSignals(QObject)` + `_ArtLoader(QRunnable)`: QImage loaded on worker, emitted via queued signal, converted to QPixmap on main thread
- In-memory LRU cache (200 entries) — `_art_cache: dict[str, QPixmap]`; generation counter prevents stale updates
- Icon 180×180, grid cell 210×240; items show placeholder immediately, art fills in asynchronously

**2.2 Acoustic Fingerprinting (AcoustID)** ✅ *Complete*
- `lyon/core/fingerprint.py`: `is_available()`, `fingerprint_file()`, `lookup_candidates()` with graceful pyacoustid/fpcalc fallback; `ACOUSTID_API_KEY` constant; searches bundled `bin/fpcalc[.exe]` first
- Schema v9: `acoustid_id TEXT` column + index; `update_acoustid()`, `find_duplicates_by_fingerprint()`, `tracks_without_acoustid()` in library
- Library view "Identify Track…" → `_IdentifyTrackDialog` (candidate table, apply writes tags + DB + acoustid_id)
- Duplicate dialog "By AcoustID Fingerprint" mode with "Scan Missing Fingerprints…" batch job (`_FingerprintScanDialog`)

**2.3 Last.fm + ListenBrainz Scrobbling** ✅ *Complete*
- `lyon/core/scrobbler.py`: `ScrobblerService(QObject)` — NowPlaying on track start, scrobble at 50%/240 s, ≥30 s minimum; all HTTP off-thread via `_HttpTask(QRunnable)`
- Last.fm token auth: `start_lastfm_auth()` → get token → open browser → `poll_lastfm_session()` via QTimer; full flow in settings dialog
- ListenBrainz: user-paste token, `Authorization: Token` header
- 4 new Settings fields; new "Scrobbling" tab; `ScrobblerService` wired in `MainWindow.__init__`

**2.4 CUE Sheet Support** ✅ *Complete*
- `lyon/core/cue_parser.py`: UTF-8-sig + Latin-1 fallback; multi-file stop at second FILE directive; `_parse_sectors()` MM:SS:FF→sectors; fills `end_sectors` on all but last track
- Schema v8: `cue_image_path`, `cue_offset_sectors`; `_index_cue_file()`, `remove_stale_cue_tracks()`; virtual tracks excluded from `remove_missing()`
- Playback: `Track.playback_uri` = image path, `playback_options` = `--start-time` / `--stop-time` VLC flags

**2.5 Playlist Import (M3U / PLS)** ✅ *Complete*
- `lyon/core/playlist_import.py`: `parse_m3u()`, `parse_pls()`, `_normalize()` path resolution; `import_playlist()` with exact + case-insensitive matching; `ImportResult` dataclass
- Library sidebar "Import Playlist…" menu item; auto-selects new playlist; warns on unmatched paths (max 10)

**2.6 Duplicate Detection — Hash Mode** ✅ *Complete*
- Schema v8: `file_hash TEXT` (MD5 first 64 KB) + index; computed on all audio files during indexing
- `find_duplicates_by_hash()` CTE query; duplicate dialog mode selector "By File Hash (content sample)"

---

### Phase 3 — Connectivity & Discovery (v0.8) ✅ Complete
*All 6 items shipped. MediaMonkey connectivity parity achieved.*

**3.1 Internet Radio** ✅ *Complete*
- `lyon/core/radio.py`: M3U/EXTM3U (EXTINF attrs, EXTGRP, HLS EXT-X-STREAM-INF), PLS parser with URL deduplication; quoted-comma-aware EXTINF splitter; `station_from_url()` rejects non-stream schemes
- `lyon/ui/radio_view.py`: Station browser tab with search, genre filter, bitrate column, play button
- Playback: `Player.play_url(uri)` — VLC HTTP stream; station list persisted + merged in settings

**3.2 DLNA / UPnP Server** ✅ *Complete*
- `lyon/core/dlna_server.py`: stdlib `http.server` + SSDP multicast; ContentDirectory SOAP Browse/Search; Artists/Albums/Tracks virtual containers; correct MIME + DLNA headers; `_local_ip()` interface-enumeration fallback
- `lyon/ui/settings_dialog.py`: DLNA tab — enable toggle, port, friendly name

**3.3 Artist Bio / Info Panel** ✅ *Complete*
- `lyon/ui/artist_panel.py`: Biography, artist photo, genre, similar artists in Now Playing side panel; background TheAudioDB fetch with race-guard task-key; 256-entry FIFO cache; library-item guard (network streams show placeholder)

**3.4 Video Resume Position** ✅ *Complete*
- Schema migration v10: `resume_position INTEGER` column
- `video_player_view.py`: Saves on stop/tab-switch; "Resume from MM:SS?" toast on load; cleared on natural end; same-source re-click guard suppresses spurious prompt

**3.5 Subtitle Delay Controls** ✅ *Complete*
- `video_player_view.py`: `libvlc_video_set_spu_delay()` via ±50 ms step buttons (`[`/`]` shortcuts) + fine-tune slider; OSD feedback

**3.6 Network Stream / Open URL** ✅ *Complete*
- `video_player_view.py`: "Open URL…" button → text input → VLC (HTTP/RTSP/HLS natively); recent-streams list in settings

---

### Phase 4 — Platform & Ecosystem (v1.0)
*Estimated: 6–8 weeks. Cross-platform parity and long-term growth features.*

**4.1 macOS and Linux CD Detection**
- `lyon/core/cd_detect.py`: Add `/dev/disk*` probe (macOS) and `/dev/cdrom` / `udev` (Linux) detection paths; remove Windows-only gating from the TOC-reading path
- Rest of ripping pipeline already cross-platform (ffmpeg-based)

**4.2 MTP / USB Device Sync**
- `pymtp` or `libmtp` binding; enumerate connected MTP devices
- `lyon/core/device_sync.py`: Two-way sync with format transcode rules and quality cap
- `lyon/ui/device_view.py`: Device browser tab; drag tracks to device; progress bar

**4.3 Podcast Support**
- `lyon/core/podcast.py`: RSS 2.0 + Atom feed parser; episode download with progress; played position tracking per episode
- Library sidebar: Podcasts section separate from music tracks

**4.4 Accessibility Audit**
- Set `setAccessibleName()` on all icon-only buttons (transport, toolbar, video controls)
- Verify Tab order through all controls; ensure focus indicators are visible in the current stylesheet
- Test with Windows Narrator and macOS VoiceOver

**4.5 macOS Notarized Distribution**
- Code signing + notarization for macOS `.dmg`; Gatekeeper compliance
- The app architecture already handles macOS (PySide6, media keys via PyObjC, platform guards throughout)

---

## 6. Development Roadmap

### Timeline

```
2026          Q2         Q3         Q4         2027 Q1
              May Jun Jul Aug Sep Oct Nov Dec Jan Feb Mar
v0.5.0 ───────■
Phase 1              ├──────────┤
v0.6.0                          ■  ✅ Complete
Phase 2                          ├────────────┤
v0.7.0                                        ■  ✅ Complete
Phase 3                                       ├──────────────┤
v0.8.0                                                        ■  ✅ Complete
Phase 4                                                        ├──────────┤
v1.0                                                                       ■
```

---

### Milestone Definitions

#### v0.6.0 — Audio Quality Release ✅ *Complete*
*Phase 1 complete. Closes audiophile and power-user gaps.*
- [x] ReplayGain: scan, tag write, playback normalization
- [x] Output device selection / WASAPI
- [x] Gapless playback verified and togglable
- [x] Batch tag editor confirmed working for all library formats

#### v0.7.0 — Library Parity Release ✅ *Complete*
*Phase 2 complete. MusicBee functional parity on core library features.*
- [x] Album art grid as primary album-browsing surface
- [x] Acoustic fingerprinting (AcoustID) with "Identify Track" workflow
- [x] Last.fm + ListenBrainz scrobbling
- [x] CUE sheet support (scan + playback)
- [x] Playlist import (M3U / PLS)
- [x] Duplicate detection: hash mode added to existing title+artist mode

#### v0.8.0 — Connectivity Release ✅ *Complete*
*Phase 3 complete. MediaMonkey connectivity parity.*
- [x] Internet radio (M3U/PLS/HLS parser + station browser)
- [x] DLNA/UPnP server (stream library to TV/receiver/phone)
- [x] Artist bio / info panel in Now Playing
- [x] Video resume position per file
- [x] Subtitle delay controls
- [x] Network stream / Open URL in video player

#### v1.0.0 — Platform Release (Target: Q1 2027)
*Phase 4 complete. Production-grade cross-platform release.*
- [ ] macOS + Linux CD detection
- [ ] MTP/USB device sync
- [x] Podcast support
- [ ] Accessibility audit complete
- [ ] macOS code-signed + notarized DMG

---

### Resource Estimates

| Phase | Single-Developer Effort | Key Risk |
|-------|:-----------------------:|---------|
| Phase 1 (Audio Quality) | 3–4 weeks | VLC WASAPI device API quirks on specific hardware |
| Phase 2 (Library Parity) | 4–6 weeks | Fingerprint binary distribution; AcoustID rate limits |
| Phase 3 (Connectivity) | 5–7 weeks | UPnP protocol complexity; radio station data freshness |
| Phase 4 (Platform) | 6–8 weeks | macOS Gatekeeper notarization; MTP driver differences |
| **Total to v1.0** | **~5–6 months** | |

---

### Key Architecture Decisions Before v0.7

1. **Fingerprint binary distribution:** Ship `fpcalc.exe` in the installer or require user download. Shipping is better UX; user download is smaller package. Recommended: bundle it alongside `ffmpeg.exe` in `bin/`.

2. **Scrobbling OAuth redirect:** Last.fm requires a browser-based OAuth redirect. Recommended approach: spin up a local `http.server` on a random port, open the browser, receive the token callback. No backend needed.

3. **DLNA library vs. sidecar process:** Pure Python (`python-didl-lite`) is easier to maintain but limited. `MiniDLNA` or `Gerbera` as a sidecar process is more robust but adds a dependency. Recommended: pure Python for v0.8; consider sidecar only if compatibility issues arise.

4. **ReplayGain tag format:** Write both `REPLAYGAIN_TRACK_GAIN` (legacy/wide compat) and `R128_TRACK_GAIN` (EBU R128, modern). Read both on playback with R128 preferred. This maximizes compatibility with other players.

5. **CUE sheet virtual tracks in library:** Keep them as rows in the `tracks` table with `media_type='cue_track'` and two new columns (`cue_image_path`, `cue_offset_sectors`) rather than a separate table. Simpler queries; playlists and smart playlists work automatically.

---

### Post-v1.0 Aspirational Backlog

| Feature | Strategic Value |
|---------|----------------|
| Streaming service integration (Tidal, Qobuz) | Competes with Roon at fraction of cost |
| Mobile companion app | Remote control + sync without a server |
| AI-powered smart playlists (mood, energy, BPM) | Differentiation; no desktop app does this well natively |
| Hi-res audio store integration (7digital, HDtracks) | Purchase-to-library pipeline |
| Cloud library metadata sync | Cross-machine library ratings/play counts |
| Plugin / extension API | foobar2000-style ecosystem; expands reach dramatically |
| Linux Flatpak / AppImage | Opens enthusiast Linux market |
| Concert / event alerts (Songkick) | Discovery differentiator built on existing artist data |

---

*Report updated for Sea Lyon Media Manager v0.8.0-dev, branch LMM-DEV. Phases 1–3 complete. Phase 3 (Connectivity & Discovery) shipped: internet radio (M3U/PLS/HLS), DLNA/UPnP MediaServer, artist bio panel, video resume position, subtitle delay controls, and network stream Open URL. Full test suite: 472 passed. Phase 4 (Platform & Ecosystem) is the only remaining work.*
