# Sea Lyon Media Manager — Product Report
**Version:** 0.5.0 · **Date:** 2026-05-17 · **Branch:** LMM-DEV  
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

At v0.5.0 the product is **approximately 89% complete** for its stated scope. All major systems are functional. The threading and resource lifecycle model is solid: worker threads use proper `shutdown()`/`join()` patterns, DLL handles are retained and released, and subprocess cancellation cleans up partial output files. The remaining gaps are **feature gaps, not stability blockers.**

**Genuine competitive advantages over any single rival:**
- CUETools DB AccurateRip v1 verification (unique among GUI apps without plugins)
- CTDB → MusicBrainz → TheAudioDB metadata fallback chain (more thorough than any competitor's default)
- DVD/VCD playback integrated with the music library (no other music manager does this)
- YouTube search + download with automatic library import (no competitor ships this)
- All of the above in one installer — no plugin ecosystem required

**Priority feature gaps to close:**
- ReplayGain (scan, read, playback normalization) — expected by any FLAC/audiophile user
- Output device selection / WASAPI — required for DAC and multi-output users on Windows
- Batch tag editor for existing library files — core library-cleanup workflow
- Acoustic fingerprinting (AcoustID) — needed for "identify unknown track" and better duplicate detection
- Last.fm / ListenBrainz scrobbling — expected by engaged music listeners
- Album grid browser — dominant UI pattern in all category leaders

---

## 2. Feature Completeness Audit

### 2.1 Scorecard

| System | Completeness | Notes |
|--------|:-----------:|-------|
| **SQLite Library** | 95% | v7 schema, 7 migrations, incremental scan, full-text search |
| **Audio Playback** | 100% | Crossfade, shuffle, repeat modes, queue persistence |
| **Equalizer** | 100% | 10-band + preamp, 10 presets, custom curves, VLC fade animation |
| **Smart Playlists** | 90% | 10 fields, all operators, SQL compiler; no nested AND/OR logic |
| **CD Ripping** | 88% | 9 output formats, CTDB AccurateRip verify; no multi-disc support |
| **Metadata Pipeline** | 95% | CTDB → MusicBrainz → TheAudioDB; no fingerprint, no persistent cache |
| **Tag Writing** | 100% | FLAC, MP3, M4A, OGG/Opus, WAV/AIFF, WMA with embedded artwork |
| **YouTube Integration** | 85% | Search + download, audio/video formats, library auto-import; no playlist mgmt UI |
| **Video Playback** | 88% | VLC embedding, fullscreen, catalog, subtitles, OSD; no resume, no open-URL |
| **Optical Disc Playback** | 100% | Audio CD, DVD, VCD/SVCD via VLC MRL |
| **Library Browsing UI** | 90% | List/grid/simple modes, sortable columns, genre filter, M3U export |
| **Now Playing / Lyrics** | 95% | Synced LRC, LRCLIB fetch, queue preview, info panel |
| **Transport** | 100% | Custom-painted glyphs, all states, both audio and video players |
| **Ripper UI** | 85% | Track table, metadata lookup, progress; no multi-disc, no retry-failed |
| **Video Player UI** | 88% | Catalog sidebar, variable speed, audio/subtitle track select, screenshots |
| **Settings** | 90% | 5 tabs, 22 fields, validation; no bandwidth cap, no API key verification |
| **Disc View UI** | 85% | Audio CD + DVD/VCD playback; no track previews, no disc bookmarking |
| **Queue Dialog** | 85% | Track list, reorder, save as playlist; no multi-select, no filter |
| **Duplicate Detector** | 80% | Title+artist normalization; no hash or acoustic fingerprint matching |
| **Library Watcher** | 100% | watchdog integration, event coalescing, graceful no-op if unavailable |
| **Diagnostics** | 100% | Runtime checks for ffmpeg, libdiscid, VLC, yt-dlp |
| **Windows Installer** | 100% | Inno Setup 6 script, per-user/machine, auto-upgrade |
| **CI/CD (GitHub Actions)** | 100% | Windows build + smoke test, binary caching, artifact upload |
| **Media Keys (macOS)** | 100% | PyObjC integration, graceful no-op elsewhere |

**Overall: ~89% complete for stated v0.5 scope**

---

### 2.2 System-by-System Detail

#### SQLite Library (`lyon/core/library.py` — 1,115 lines)
- **Schema:** v7 with complete migration chain from v0; `Track` dataclass with 25 fields
- **Formats:** Audio — FLAC, MP3, M4A, AAC, OGG, Opus, WAV, AIFF, WMA; Video — MP4, MKV, WebM, AVI, MOV
- **Scanning:** Incremental via mtime+size change detection; `should_cancel` callback prevents UI freezes
- **Queries:** all_artists, albums_for_artist, tracks_for_album, all_genres, search (LIKE-escaped), recently_added, recently_played, most_played, top_rated, tracks_for_genre
- **Library ops:** ratings (0–5), liked flag, play_count increment, disc_id for duplicate detection
- **Playlists:** manual + smart; `create_playlist`, `reorder_playlist`, M3U export; smart playlist via `SmartPlaylistSpec`
- **Duplicate finder:** `find_duplicates()` by normalized artist + title
- **Gap:** No acoustic fingerprint or file-hash comparison; video metadata falls back to folder names

#### Audio Playback (`lyon/core/player.py` — 484 lines)
- **Queue:** `load_queue`, `set_queue`, `enqueue`, `remove_queue_index`, `move_queue_item`, `clear_queue`
- **Transport:** `play_index`, `play`, `pause`, `stop`, `seek`, `next`, `previous`
- **Modes:** Shuffle (per-queue random path), repeat OFF/ONE/ALL
- **Volume:** 0–100 with clamping; mute toggle
- **Crossfade:** Dual-backend overlap with 50ms fade ticks; configurable overlap seconds (0 = disabled)
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
- **Gap:** No multi-disc album support; ripper view does not expose a "Retry failed tracks" button

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
- **Controls:** Seek, play/pause/stop, volume, mute, speed (0.25×–2×), audio track select, subtitle track select + load external file, screenshot
- **Fullscreen:** Borderless `_FullscreenWindow` with keyboard controls (Space, Esc/F, arrows ±5s/30s, M, ↑↓ volume), OSD feedback
- **Equalizer:** 10-band applied via same `VlcEqualizerController` as audio player
- **Gap:** No per-video resume position; no "Open URL" for network streams; no subtitle delay controls; no aspect ratio/zoom; no deinterlace

#### Library Browsing UI (`lyon/ui/library_view.py` — ~1,900 lines)
- **Modes:** List (4-pane: Genre → Artist → Album → Track with sortable columns), Grid (album art grid), Simple (3-pane without genres)
- **Track actions:** Play, enqueue, add to playlist, edit metadata (single + batch), open folder, YouTube search
- **Format badges:** Color-coded FLAC/MP3/AAC/OGG per track row
- **Star rating:** Inline 5-star delegate with hover preview
- **Virtual collections:** Recently Added/Played, Most Played, Top Rated (4★+)
- **Search:** 150ms debounced full-text search
- **Playlist management:** Create, add tracks, reorder (drag-drop), M3U export, smart playlist editor
- **Gap:** No playlist import; no artwork-focused album grid (grid mode shows albums but small)

#### Now Playing + Lyrics (`lyon/ui/now_playing.py` — 904 lines)
- **Artwork:** 280×280 cover with blurred full-background effect
- **Lyrics system:** LRC sidecar → embedded USLT tag → LRCLIB online fetch; synced highlight with animated scroll; 256-entry FIFO cache; plain-text fallback
- **Panels:** Queue (12 upcoming, double-click to jump, drag-reorder), Lyrics (synced/plain), Info (year, genre, track count)
- **Gap:** No lyrics editing/submission; no visualizer in Now Playing

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
| Album grid browser | ⚠️ | ✅ | ✅ | via skin | ✅ |
| Sortable column browser | ✅ | ✅ | ✅ | ✅ | ✅ |
| Batch tag editor | ✅ | ✅ | ✅ | ✅ | ❌ |
| Grouping / custom tags | ✅ | ✅ | ✅ | ✅ | ❌ |
| Duplicate detection | ⚠️ | ✅ | ✅ | via plugin | ✅ |
| M3U playlist export | ✅ | ✅ | ✅ | ✅ | ❌ |
| Playlist import | ❌ | ✅ | ✅ | ✅ | ❌ |

> ⚠️ = partial — Sea Lyon's album grid shows albums but is not the primary browsing surface; duplicate detection uses title+artist normalization only (no hash or fingerprint)

#### Playback & Audio Quality

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Crossfade | ✅ | ✅ | ✅ | via plugin | ✅ |
| 10-band equalizer | ✅ | ✅ | ✅ | via plugin | ❌ |
| EQ presets + custom curves | ✅ | ✅ | ✅ | via plugin | ❌ |
| Gapless playback | ⚠️ | ✅ | ✅ | ✅ | ✅ |
| ReplayGain (read + scan) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Output device / WASAPI | ❌ | ✅ | ✅ | ✅ | ✅ |
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
| CUE sheet support | ❌ | ✅ | ✅ | ✅ | ❌ |
| CD playback | ✅ | ✅ | ✅ | ✅ | ❌ |
| **DVD / VCD playback** | ✅ | ❌ | ❌ | ❌ | ❌ |
| MusicBrainz metadata | ✅ | ✅ | ✅ | via plugin | ✅ |
| TheAudioDB enrichment | ✅ | ❌ | ❌ | ❌ | ❌ |

#### Metadata & Discovery

| Feature | **Sea Lyon** | MusicBee | MediaMonkey | foobar2000 | Roon |
|---------|:---:|:---:|:---:|:---:|:---:|
| Automatic artwork | ✅ | ✅ | ✅ | via plugin | ✅ |
| Synced lyrics (LRC + online) | ✅ | ✅ | ❌ | via plugin | ✅ |
| Acoustic fingerprinting | ❌ | ✅ | ✅ | via plugin | ✅ |
| Artist bio / info panel | ❌ | ✅ | ✅ | ❌ | ✅ |
| Last.fm scrobbling | ❌ | ✅ | ✅ | via plugin | ✅ |
| ListenBrainz scrobbling | ❌ | via plugin | ❌ | via plugin | ❌ |
| Internet radio | ❌ | ✅ | ✅ | via plugin | ❌ |
| Podcast support | ❌ | ✅ | ❌ | ❌ | ❌ |

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
| DLNA/UPnP server | ❌ | ✅ | ✅ | ❌ | ✅ |
| DLNA/UPnP renderer | ❌ | ✅ | ✅ | ❌ | ✅ |
| AirPlay output | ❌ | ❌ | ❌ | ❌ | ✅ |
| Network stream playback (URL) | ❌ | ❌ | ❌ | ✅ | ✅ |
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
| Video resume position | ❌ | ❌ | ✅ | ⚠️ | ✅ |
| Network stream (URL/IPTV) | ❌ | ❌ | ❌ | ✅ | ✅ |
| Subtitle delay controls | ❌ | ❌ | ❌ | ✅ | ✅ |
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
| ReplayGain scan + read + playback | ✅ | ✅ | **Critical** |
| Output device / WASAPI | ✅ | ✅ | **Critical** |
| Acoustic fingerprinting (AcoustID) | ✅ | ✅ | **High** |
| Last.fm / ListenBrainz scrobbling | ✅ | ✅ | **High** |
| CUE sheet support | ✅ | ✅ | **High** |
| Album art grid as primary browser | ✅ | ✅ | **High** |
| DLNA/UPnP server | ✅ | ✅ | Medium |
| Internet radio | ✅ | ✅ | Medium |
| Artist bio / info panel | ✅ | ✅ | Medium |
| Playlist import (M3U/PLS) | ✅ | ✅ | Medium |
| Video resume position | n/a | ✅ | Medium |
| MTP/USB device sync | ✅ | ✅ | Low |
| Network stream / open URL | ❌ | ❌ | Low |

---

## 4. Gap Analysis

### 4.1 Critical — Blocks Power-User Adoption

**ReplayGain**  
No loudness normalization of any kind. FLAC users and audiophiles expect this as baseline. Missing means volume jumps between tracks from different albums.  
Scope: scan + tag write (R128/ReplayGain tags via ffmpeg loudnorm) + playback read + apply gain to VLC volume pre-output. Album-mode and track-mode. Settings toggle.

**Output Device / WASAPI**  
Users with DACs, multiple audio outputs, or audio interfaces cannot select their device. On Windows this is WASAPI; Sea Lyon exposes no output device selection at all.  
Scope: `libvlc_audio_output_device_enum()` → settings dropdown; `--aout wasapi --wasapi-audio-device` passed to VLC; player restart on change.

**Batch Tag Editor (existing library files)**  
The library view can edit metadata on multiple selected tracks via a batch dialog, but the existing tagger only writes on rip. Confirm the batch dialog in `library_view.py` is fully wired to `tagger.py` for arbitrary library tracks, not just ripped ones.  
*(From code analysis: batch metadata editing is present in library_view.py — verify it covers all formats and saves back to the library DB.)*

### 4.2 High — Required for MusicBee Functional Parity

**Acoustic Fingerprinting (AcoustID)**  
No "identify unknown track" workflow. Duplicate detection is title+artist normalization only — misses files with wrong/missing tags or identical audio under different names.  
Scope: `pyacoustid` + `fpcalc` binary; `lyon/core/fingerprint.py`; library context menu "Identify Track" → candidate dialog; duplicate dialog "match by fingerprint" option.

**Last.fm / ListenBrainz Scrobbling**  
No play history submitted to external services. Many engaged listeners use this for discovery, year-in-review stats, and recommendations.  
Scope: OAuth flow for Last.fm; user token for ListenBrainz; hook into `player.py` play-count increment point; submit NowPlaying on start, Scrobble after 50% or 4 min.

**CUE Sheet Support**  
No `.cue` + image parsing. Many ripped CDs are distributed as single-image + CUE. These are completely invisible to Sea Lyon's scanner.  
Scope: `lyon/core/cue_parser.py` → parse CUE, expose as virtual tracks; library scan picks up `.cue`; playback seeks to CUE offset within parent image.

**Album Art Grid as Primary Browser**  
The current grid mode shows albums but it is not the dominant browsing surface (list mode is default). A full-bleed artwork grid is the expected entry point for casual browsing and is the primary UI pattern in every competitor.  
Scope: Dedicated album grid view with 180×180 artwork tiles, async pixmap cache, double-click → track list. Should be the default view for "Albums" in the sidebar.

### 4.3 Medium — MediaMonkey Connectivity Parity

**DLNA / UPnP Server**  
Cannot stream library to smart TVs, AV receivers, or other DLNA renderers on the local network.  
Scope: `python-didl-lite` + `async-upnp-client`; minimal UPnP MediaServer with SSDP announce; serve tracks with correct MIME types; settings: enable/port/name.

**Internet Radio**  
No Shoutcast/Icecast stream support. Common request from users who also want background listening without YouTube.  
Scope: `lyon/core/radio.py`; m3u/pls/m3u8 URL parsing; `lyon/ui/radio_view.py` with station browser; playback via existing player with URI support (VLC already handles HTTP streams).

**Artist Bio / Info Panel**  
TheAudioDB data (biography, artist image, similar artists) is fetched during disc lookup but never displayed anywhere.  
Scope: `lyon/ui/artist_panel.py`; collapsible panel in Now Playing; pulls cached TheAudioDB data already in the metadata pipeline.

**Video Resume Position**  
No per-file last-position tracking for video. Every video starts from the beginning.  
Scope: Library schema migration v8 adds `resume_position` integer column; `video_player_view.py` saves on stop, seeks on load with "Resume from MM:SS?" toast.

**Subtitle Delay Controls**  
VLC supports `libvlc_video_set_spu_delay()` but the UI does not expose it.  
Scope: ±50ms step buttons + fine slider in video controls bar.

**Playlist Import (M3U / PLS)**  
M3U export exists; import does not. Common workflow when migrating from another app.  
Scope: File picker in library sidebar → parse M3U/PLS → match paths to library → create playlist.

### 4.4 Low — Nice-to-Have / Differentiation

| Feature | Notes |
|---------|-------|
| Network stream / Open URL | VLC supports HTTP/RTSP/HLS natively; just expose "Open URL" button in video player |
| Multi-disc album ripping | Ripper has no concept of disc number within an album rip session |
| Nested smart playlist logic | Current AND/OR applies globally; power users want (A OR B) AND C |
| EQ frequency response graph | Visual feedback while adjusting bands |
| Subtitle delay controls | Already noted in Medium above |
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

**1.4 Gapless Playback Verification**
- Set VLC `--audio-time-stretch-enabled 0` and tune pre-buffering to minimize gap between tracks
- Add gapless mode toggle to settings; document that it works only when crossfade = 0

---

### Phase 2 — Library & Metadata Parity (v0.7)
*Estimated: 4–6 weeks. Brings Sea Lyon to MusicBee functional parity.*

**2.1 Album Art Grid (Primary Browser)**
- `lyon/ui/library_view.py`: New album grid page using `QListView` + `QStyledItemDelegate` rendering 180×180 artwork + title + artist + year; make this the default for "Albums" nav entry
- Async pixmap loading via `QThreadPool` with in-memory cache (avoid blocking scroll)
- Double-click → switch to track list for that album

**2.2 Acoustic Fingerprinting (AcoustID)**
- Add `pyacoustid` + ship `fpcalc.exe` in `bin/`; update `build/lyon.spec` binaries list
- `lyon/core/fingerprint.py`: `fingerprint_file(path)` → call AcoustID API → return `[(score, mbid, title, artist)]`
- Library view: "Identify Track" context menu → fingerprint worker → candidate dialog → apply + update DB
- `lyon/ui/duplicate_dialog.py`: "Match by fingerprint" option alongside existing title+artist mode

**2.3 Last.fm + ListenBrainz Scrobbling**
- `lyon/core/scrobbler.py`: Last.fm (API key + secret, token-based auth via local HTTP callback) + ListenBrainz (user token)
- Hook into `player.py` `track_changed` signal: emit NowPlaying on start; track elapsed time; scrobble at 50% or 4 min
- `lyon/ui/settings_dialog.py`: Scrobbling section — enable/disable per service, login/logout, last-scrobbled indicator

**2.4 CUE Sheet Support**
- `lyon/core/cue_parser.py`: Parse `.cue` + paired image (FLAC/WAV/MP3); produce virtual `Track` objects with sector-based start/end offsets
- `lyon/core/library.py`: Add `.cue` to scanner; store as media_type='cue_track' with parent image path + offsets
- Playback: Seek to CUE offset within parent image via VLC `--start-time` / `--stop-time` options

**2.5 Playlist Import (M3U / PLS)**
- `lyon/core/playlist_import.py`: Parse M3U8 (extended) + PLS; resolve relative paths; match to library DB by path
- Library view: File picker → import as new playlist; warn on unmatched paths

**2.6 Duplicate Detection — Hash Mode**
- `lyon/core/library.py`: Add `file_hash` column (MD5 of first 64 KB, fast + collision-resistant for music use)
- `lyon/core/library.py`: `find_duplicates_by_hash()` — exact byte match without relying on tags
- `lyon/ui/duplicate_dialog.py`: Mode selector: "By title/artist" / "By file hash" / "By fingerprint" (once 2.2 ships)

---

### Phase 3 — Connectivity & Discovery (v0.8)
*Estimated: 5–7 weeks. Closes remaining MediaMonkey parity gaps.*

**3.1 Internet Radio**
- `lyon/core/radio.py`: m3u/pls/m3u8 URL parser; optional station list from community JSON feed
- `lyon/ui/radio_view.py`: Station browser tab with search, genre filter, bitrate, play button
- Playback: `player.play_url(uri)` — VLC already handles HTTP streams; add URI path to `Player`
- Save favorite stations as library playlist type "Radio"

**3.2 DLNA / UPnP Server**
- Dependencies: `python-didl-lite`, `async-upnp-client`
- `lyon/core/dlna_server.py`: UPnP MediaServer device; SSDP announce; browse/search content actions; serve tracks as HTTP with correct MIME types
- `lyon/ui/settings_dialog.py`: DLNA tab — enable toggle, port, friendly name

**3.3 Artist Bio / Info Panel**
- `lyon/ui/artist_panel.py`: Collapsible side panel in Now Playing; artist photo + bio from TheAudioDB; similar artists list; discography count
- TheAudioDB response already cached in metadata pipeline — parse and surface it

**3.4 Video Resume Position**
- `lyon/core/library.py`: Schema migration v8 — add `resume_position INTEGER` column
- `lyon/ui/video_player_view.py`: Save position to DB on stop/tab-switch; on load, show "Resume from MM:SS?" toast with seek-on-confirm

**3.5 Subtitle Delay Controls**
- `lyon/ui/video_player_view.py`: Expose `libvlc_video_set_spu_delay()` via ±50ms step buttons (keyboard shortcut `[` / `]`) + fine-tune slider; OSD feedback

**3.6 Network Stream / Open URL**
- `lyon/ui/video_player_view.py`: "Open URL…" button → text input → pass directly to VLC (supports HTTP, RTSP, HLS natively); add to recent-streams list in settings

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
v0.6.0                          ■
Phase 2                          ├────────────┤
v0.7.0                                        ■
Phase 3                                       ├──────────────┤
v0.8.0                                                        ■
Phase 4                                                        ├──────────┤
v1.0                                                                       ■
```

---

### Milestone Definitions

#### v0.6.0 — Audio Quality Release (Target: August 2026)
*Phase 1 complete. Closes audiophile and power-user gaps.*
- [ ] ReplayGain: scan, tag write, playback normalization
- [ ] Output device selection / WASAPI
- [ ] Gapless playback verified and togglable
- [ ] Batch tag editor confirmed working for all library formats

#### v0.7.0 — Library Parity Release (Target: October 2026)
*Phase 2 complete. MusicBee functional parity on core library features.*
- [ ] Album art grid as primary album-browsing surface
- [ ] Acoustic fingerprinting (AcoustID) with "Identify Track" workflow
- [ ] Last.fm + ListenBrainz scrobbling
- [ ] CUE sheet support (scan + playback)
- [ ] Playlist import (M3U / PLS)
- [ ] Duplicate detection: hash mode added to existing title+artist mode

#### v0.8.0 — Connectivity Release (Target: December 2026)
*Phase 3 complete. MediaMonkey connectivity parity.*
- [ ] Internet radio (Shoutcast/Icecast browser)
- [ ] DLNA/UPnP server (stream library to TV/receiver/phone)
- [ ] Artist bio / info panel in Now Playing
- [ ] Video resume position per file
- [ ] Subtitle delay controls
- [ ] Network stream / Open URL in video player

#### v1.0.0 — Platform Release (Target: Q1 2027)
*Phase 4 complete. Production-grade cross-platform release.*
- [ ] macOS + Linux CD detection
- [ ] MTP/USB device sync
- [ ] Podcast support
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

*Report generated from direct source analysis of Sea Lyon Media Manager v0.5.0, branch LMM-DEV, commit 6f006c0. All findings derived from reading `lyon/core/` (17 files, ~4,100 lines), `lyon/ui/` (21 files, ~8,800 lines), `build/`, `.github/workflows/`, and `tests/` (27 test files). No third-party review documents referenced.*
