# Report 3: Feature Parity With Market-Leading Products

Review date: 2026-05-15

Scope: comparison against current features advertised/documented by MediaMonkey, MusicBee, Roon, Plex/Plexamp, JRiver Media Center, and VLC. Sea Lyon is strongest today as a Windows-focused CD ripper plus local media player; the biggest parity gaps are library depth, device/remote sync, advanced playback, and discovery.

## Current Sea Lyon Strengths

- Multi-format CD ripping with metadata lookup and CTDB/AccurateRip-style verification.
- SQLite local library with audio/video scanning.
- VLC-backed audio/video playback with 10-band EQ.
- YouTube search/download integration through yt-dlp.
- Runtime diagnostics and Windows packaging intent.

## Competitive Gaps and Suggested Fixes

### 1. Library model: playlists, ratings, play history, and custom fields

Market signal: MediaMonkey advertises collections, standard tags, custom fields, duplicate removal, auto-organize/rename, device sync of ratings and play history, cloud backup, DLNA sharing, and casting. Source: <https://www.mediamonkey.com/windows>.

Current gap: `lyon/core/library.py` stores one `tracks` table with no playlists, ratings, play counts, last played, favorites, custom tags, collection membership, or duplicate groups.

Suggested fix:

- Add migrations for `playlists`, `playlist_tracks`, `track_stats`, `track_user_metadata`, and `collections`.
- Add rating, favorite, play count, last played, date modified, file hash, and album sort fields.
- Add duplicate finder by file hash, acoustic fingerprint later, and metadata similarity.

### 2. Watched folders and incremental scanning

Market signal: leading managers update libraries automatically and scale to very large collections. MediaMonkey positions itself around managing thousands of music tracks and videos. Source: <https://www.mediamonkey.com/windows>.

Current gap: scans are manual/startup batch walks through `Library.scan_paths()`.

Suggested fix:

- Add file-system monitoring with `watchdog`.
- Track folder scan state and file mtimes.
- Process changes incrementally in a worker queue with user-visible progress.

### 3. Metadata enrichment and tag editing

Market signal: Roon emphasizes rich credits, artist relationships, genres, lyrics, tour dates, artwork, metadata cleanup, and discovery. Source: <https://help.roonlabs.com/portal/en/kb/articles/about-roon>. MediaMonkey advertises automatic metadata, artwork, and lyrics lookup. Source: <https://www.mediamonkey.com/windows>. MusicBee FAQ points users to auto-tagging and manual tag repair for album grouping. Source: <https://getmusicbee.com/help/faq/>.

Current gap: Sea Lyon has good CD metadata lookup, but no batch tag editor, lyrics, artist bios, credits, relationship graph, release version handling, or existing-file auto-tag workflow.

Suggested fix:

- Add a batch tag editor and "Identify album" workflow for selected files.
- Store lyrics, artist bio, release ID, recording ID, composer, conductor, label, catalog number, and release country.
- Add conflict UI that shows existing tags vs provider metadata before writing.

### 4. Playback quality: ReplayGain, gapless, crossfade, output modes

Market signal: MediaMonkey lists 10-band EQ, DSP add-ons, volume leveling, and WASAPI. Source: <https://www.mediamonkey.com/windows>. JRiver highlights bit-perfect playback, WASAPI, ASIO, VST, DSD, rich DSP, and memory playback. Source: <https://www.jriver.com/audio.html>. Plex music documents loudness leveling and Sweet Fades. Source: <https://support.plex.tv/articles/205744257-getting-started-with-plex-music/>.

Current gap: Sea Lyon has EQ but no ReplayGain/loudness analysis, crossfade, gapless guarantee, output-device selection, WASAPI/ASIO mode, DSP chain, or signal-path display.

Suggested fix:

- Add ReplayGain scan/read/write and playback gain modes: off, track, album, smart.
- Add gapless and crossfade support or document backend limits.
- Add output device selection and a "signal path" panel for codec, sample rate, bit depth, EQ, and output backend.

### 5. Device sync, remote access, and casting

Market signal: MediaMonkey supports device sync, Wi-Fi sync, cloud storage, UPnP/DLNA sharing, and Cast. Source: <https://www.mediamonkey.com/windows>. Roon ARC provides remote access to a personalized library and supports CarPlay/Android Auto. Source: <https://roon.app/en/arc?trk=public_post-text>. VLC is cross-platform and plays files, discs, devices, streams, and common network protocols. Source: <https://images.videolan.org/vlc/>.

Current gap: Sea Lyon is local-desktop only.

Suggested fix:

- Add MTP/USB sync profiles with transcoding rules and playlist sync.
- Add DLNA/UPnP server or renderer support.
- Add local-network remote control API before attempting full mobile apps.
- Longer term: companion mobile app or web UI for remote playback/control.

### 6. Video parity

Market signal: VLC plays most multimedia files, DVDs, Audio CDs, VCDs, and streaming protocols. Source: <https://images.videolan.org/vlc/>. JRiver positions video around high-quality playback, automatic filter setup, TV, theater view, and remote-friendly use. Source: <https://jriver.com/video.html>.

Current gap: Sea Lyon has local file playback, subtitles, track selection, screenshots, and catalog cards, but lacks network streams, disc playback, resume positions, playlists, cast/render targets, subtitle delay/sync, and a 10-foot/theater mode.

Suggested fix:

- Add URL/network stream open.
- Store per-video resume position and subtitle/audio preferences.
- Add playlist/queue support for videos.
- Add subtitle delay and audio delay controls.
- Later: DLNA/Cast output and theater mode.

### 7. Discovery and smart listening

Market signal: Plex sonic analysis supports sonically similar artists/albums/tracks, Track Radio, and suggested mixes based on local audio analysis. Source: <https://support.plex.tv/articles/sonic-analysis-music/>. Roon emphasizes metadata-driven discovery and recommendations. Source: <https://help.roonlabs.com/portal/en/kb/articles/about-roon>.

Current gap: Sea Lyon search is text-based; there is no radio, recommendation, similarity, scrobbling, or listening-history-driven experience.

Suggested fix:

- First implement play history, ratings, and smart playlists.
- Add "Track radio" from genre/year/artist/album metadata.
- Later add local audio feature extraction for BPM, mood, key, energy, and similarity.

### 8. Podcasts, internet radio, and online services

Market signal: MediaMonkey advertises podcasts, online radio, related YouTube content, and Spotify playlist sync. Source: <https://www.mediamonkey.com/windows>.

Current gap: Sea Lyon has YouTube search/download but no podcast subscriptions, RSS, internet radio directory, streaming-service playlist import, or scrobbling.

Suggested fix:

- Add podcast RSS subscriptions and episode download management.
- Add internet radio stream bookmarks.
- Add Last.fm/ListenBrainz scrobbling after play-history schema exists.

## Suggested Roadmap

P0 Stabilize: fix packaging root, thread shutdown, rip cancellation, and PySide CI smoke tests.

P1 Library foundation: watched folders, playlists, ratings, play history, duplicate finder, batch tag editor.

P2 Playback polish: ReplayGain, gapless/crossfade, output device selection, signal path, per-video resume.

P3 Sync and sharing: USB/MTP sync, DLNA/UPnP, local remote API, cloud backup/export.

P4 Discovery: lyrics, credits, artist bios, smart playlists, radio, sonic similarity, podcasts, scrobbling.
