# Sea Lyon Media Manager — Privacy Policy

**Last updated:** 2026-05-31

## Summary

Sea Lyon Media Manager **does not collect telemetry of any kind**. The
application does not phone home, does not report crashes to a remote
service, does not collect usage statistics, and does not transmit your
library contents to the developers.

Crash logs and diagnostics are written **only to your local machine**
under `%APPDATA%\LyonMusicManager\logs\` on Windows or
`~/Library/Application Support/LyonMusicManager/logs/` on macOS, and are
never uploaded automatically. If you wish to share diagnostics with a
support contact, use Help → Copy Diagnostics to copy a redacted bundle to
your clipboard.

## Data stored on your machine

The application stores the following on your computer, locally:

On macOS, the same files live under
`~/Library/Application Support/LyonMusicManager/`.

- **Library database** — `%APPDATA%\LyonMusicManager\library.sqlite3`.
  Catalog of files in folders you have added to the library, their tag
  metadata, ratings, play counts, and playlists.
- **Settings** — `%APPDATA%\LyonMusicManager\settings.json`. Your
  preferences, scrobbler tokens (Last.fm session key, ListenBrainz
  token) if you signed in, your saved radio / podcast feeds, and the
  selected browser name for optional YouTube browser-session downloads.
  Sea Lyon does not store browser cookies. The file is chmodded to
  owner-read-only on Windows.
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
| `theaudiodb.com` | Supplemental metadata (artist images, descriptions) | Metadata lookup is enabled and the TheAudioDB API key field is not blank. | Artist / album name. |
| `lrclib.net` | Lyric lookup | "Fetch lyrics online" is enabled in Settings. | Track title + artist (optionally album + duration). |
| `ws.audioscrobbler.com` (Last.fm) | Scrobble + Now Playing | You signed in to Last.fm and enabled scrobbling. | Track title, artist, album, timestamp, session key. |
| `api.listenbrainz.org` | Scrobble + Now Playing | You entered a ListenBrainz token and enabled scrobbling. | Track title, artist, album, timestamp, token. |
| Podcast feed URLs (whatever you subscribe to) | RSS / Atom feed refresh | You subscribe to a podcast or refresh feeds. | HTTP request to the host you subscribed to. |
| Radio stream URLs | Audio playback | You play an Internet radio station. | HTTP request to the stream host. |
| `youtube.com` / `youtu.be` and YouTube CDN hosts (via yt-dlp) | Search, metadata extraction, player JavaScript retrieval, and download | You use the YouTube features. | Query strings, video IDs, normal HTTP request data, and, only when browser-session mode is enabled, applicable YouTube cookies read by yt-dlp from the selected signed-in browser. |
| Software update appcast (`drshoctopus.github.io`) | Check for newer release | App startup, no more than once every 24 h, only if "Check for updates" is enabled. | A plain GET request; no user data sent. |
| `github.com/.../releases` (via your browser) | Download installer | You clicked "Download Now" in the update dialog. | Your browser navigates to a public release URL. |

## YouTube browser-session mode and JavaScript challenges

The YouTube features are powered by yt-dlp. For age-restricted or
otherwise account-gated videos you are authorized to access, you can
enable **Use browser session for restricted videos** in Settings →
YouTube and choose a supported browser. Sea Lyon stores only that browser
choice. During a download, yt-dlp reads the selected browser's local
cookie store and sends applicable YouTube cookies to YouTube so YouTube
can authenticate the request. Sea Lyon does not copy those cookies into
`settings.json`, the library database, or its cache.

Some YouTube downloads also require solving player-signature JavaScript
challenges before media URLs are available. Sea Lyon enables yt-dlp's
Deno/Node runtime support, includes the `yt-dlp-ejs` solver package, and
packages a pinned Deno runtime in release builds. The JavaScript runtime
runs locally. It does not send telemetry to Sea Lyon's authors; it is
used to execute solver code and YouTube player code needed by yt-dlp for
the download you initiated.

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

Diagnostics do not include browser cookie contents. They may include the
selected YouTube browser name and yt-dlp error text, which can be useful
for troubleshooting browser permission or JavaScript-runtime failures.

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
