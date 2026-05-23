# Sea Lyon Media Manager — Privacy Policy

**Last updated:** 2026

## Summary

Sea Lyon Media Manager **does not collect telemetry of any kind**. The
application does not phone home, does not report crashes to a remote
service, does not collect usage statistics, and does not transmit your
library contents to the developers.

Crash logs and diagnostics are written **only to your local machine**
under `%APPDATA%\LyonMusicManager\logs\` and are never uploaded
automatically. If you wish to share diagnostics with a support contact,
use Help → Copy Diagnostics to copy a redacted bundle to your clipboard.

## Data stored on your machine

The application stores the following on your computer, locally:

- **Library database** — `%APPDATA%\LyonMusicManager\library.sqlite3`.
  Catalog of files in folders you have added to the library, their tag
  metadata, ratings, play counts, and playlists.
- **Settings** — `%APPDATA%\LyonMusicManager\settings.json`. Your
  preferences, scrobbler tokens (Last.fm session key, ListenBrainz
  token) if you signed in, and your saved radio / podcast feeds. The
  file is chmodded to owner-read-only on Windows.
- **Cache** — `%APPDATA%\LyonMusicManager\cache\`. Album artwork and
  metadata responses, refreshable from upstream sources.
- **Logs** — `%APPDATA%\LyonMusicManager\logs\`. Rotating application
  log (10 MB × 5 files) and an optional metadata diagnostics log.

None of these are transmitted off your machine by the application.

## Outbound network calls

The application makes outbound network calls **only when you take an
action that requires them**. Every outbound endpoint is listed below.

| Endpoint | Purpose | When it fires | Data sent |
|---|---|---|---|
| `musicbrainz.org` | Album / track metadata lookup | You insert a CD or trigger a metadata lookup. | Disc ID or release MBID; User-Agent containing the app name, version, and the MusicBrainz contact URL configured in Settings. |
| `coverartarchive.org` | Album cover art download | A MusicBrainz lookup returns a release. | Release MBID. |
| `db.cuetools.net` | Rip verification (CTDB) | You enable CTDB verification while ripping. | Disc CTDB ID. |
| `acoustid.org` (indirect via `pyacoustid`) | Audio fingerprint lookup | You explicitly fingerprint a track. | Chromaprint hash + track duration. |
| `theaudiodb.com` | Supplemental metadata (artist images, descriptions) | You have entered an API key and metadata lookup is enabled. | Artist / album name. |
| `lrclib.net` | Lyric lookup | "Fetch lyrics online" is enabled in Settings. | Track title + artist (optionally album + duration). |
| `ws.audioscrobbler.com` (Last.fm) | Scrobble + Now Playing | You signed in to Last.fm and enabled scrobbling. | Track title, artist, album, timestamp, session key. |
| `api.listenbrainz.org` | Scrobble + Now Playing | You entered a ListenBrainz token and enabled scrobbling. | Track title, artist, album, timestamp, token. |
| Podcast feed URLs (whatever you subscribe to) | RSS / Atom feed refresh | You subscribe to a podcast or refresh feeds. | HTTP request to the host you subscribed to. |
| Radio stream URLs | Audio playback | You play an Internet radio station. | HTTP request to the stream host. |
| `youtube.com` / `youtu.be` and CDN hosts (via yt-dlp) | Search and download | You use the YouTube features. | Query strings or video IDs you searched for. |
| Software update appcast (`drshoctopus.github.io`) | Check for newer release | App startup, no more than once every 24 h, only if "Check for updates" is enabled. | A plain GET request; no user data sent. |
| `github.com/.../releases` (via your browser) | Download installer | You clicked "Download Now" in the update dialog. | Your browser navigates to a public release URL. |

## What is included in a diagnostics bundle

Help → Copy Diagnostics produces a plain-text bundle you can paste into a
support email. It includes:

- Application version, Python version, OS version.
- Result of dependency checks (ffmpeg, VLC, libdiscid, fpcalc presence).
- The last 1 MB of the main application log.
- The last 1 MB of the metadata diagnostics log, if present.
- Your `settings.json`, with the following keys redacted as `<redacted>`:
  - `lastfm_session_key`
  - `listenbrainz_token`
  - `theaudiodb_api_key`

Library paths, podcast feed URLs, and radio station URLs are **not**
redacted, since they are often necessary for debugging. Review the
bundle before sharing if those paths are sensitive.

## Children

The Software is not directed to children under 13 and is not intended
for use by them.

## Changes to this policy

If this policy changes, the new version will ship with a corresponding
update of the application. The "Last updated" date at the top of this
file reflects the current version.

## Contact

For privacy questions, open an issue at
<https://github.com/DrShoctopus/Sea-Lyon-Media-Manager/issues>.
