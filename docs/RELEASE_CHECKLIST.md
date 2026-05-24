# Sea Lyon Media Manager — Release Smoke-Test Checklist

Use this sheet for every public release tag (including release candidates).
Copy it into the PR / release issue, fill in pass / fail / notes, and only
publish the GitHub Release when every required row is green.

**Release:** `vX.Y.Z`
**Tested by:**
**Date:**
**Installer SHA-256:** _(from `SeaLyonMediaManager-X.Y.Z-SHA256SUMS.txt`)_

## How to run

1. Pull the draft Release from GitHub Actions
   (or the workflow_dispatch artifact for an RC).
2. Verify the SHA-256 of the installer matches the SHA256SUMS file.
3. Run each section on a **clean Windows 10 22H2** VM and a **clean
   Windows 11 23H2 (or newer)** VM. "Clean" means no
   `%APPDATA%\LyonMusicManager\` directory.
4. Tick rows in order; do not skip ahead unless the row's note says so.
5. File any failure as a `release-blocker` issue and re-cut the tag.

---

## A. Installer

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| A1 | Double-click `SeaLyonMediaManager-X.Y.Z-Setup.exe`. | SmartScreen warns "Windows protected your PC". | ☐ | ☐ |
| A2 | Click **More info → Run anyway**. | UAC prompt appears. | ☐ | ☐ |
| A3 | Accept UAC. | Inno Setup wizard opens, splash image visible on left. | ☐ | ☐ |
| A4 | Click Next on each page. | License (EULA.txt) → Third-Party Notices → Install Location → Ready → Installing → Finish. | ☐ | ☐ |
| A5 | EULA page shows MIT + user-responsibility tail. | Required-accept radio enabled. | ☐ | ☐ |
| A6 | Third-Party Notices page shows VLC, Qt, ffmpeg (GPL note), libdiscid, etc. | Scrollable and readable. | ☐ | ☐ |
| A7 | Installer finishes; "Launch Sea Lyon Media Manager" checkbox visible. | Default to "Launch" checked. | ☐ | ☐ |
| A8 | Check Start Menu group "Sea Lyon Media Manager". | Shortcut + uninstaller present. | ☐ | ☐ |
| A9 | Verify registry key `HKCU\Software\Sea Lyon\Media Manager`. | `InstalledVersion`, `InstallPath`, `AppcastUrl` populated. | ☐ | ☐ |
| A10 | Verify `%APPDATA%\LyonMusicManager\logs\sea-lyon.log` exists. | File present after first launch. | ☐ | ☐ |

## B. First-run flow

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| B1 | Launch app from Start Menu. | Splash → main window. SmartScreen advisory toast appears once. | ☐ | ☐ |
| B2 | First-run wizard appears. | Music root + library folders fields visible. | ☐ | ☐ |
| B3 | Choose a music folder containing at least 20 audio files. | Wizard accepts; library scan starts. | ☐ | ☐ |
| B4 | After Finish, library tab populates. | Tracks visible within ~10s for a small library. | ☐ | ☐ |
| B5 | Re-launch the app (close and reopen). | First-run wizard does NOT reappear. SmartScreen toast does NOT reappear. | ☐ | ☐ |

## C. Audio playback

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| C1 | Double-click a FLAC or MP3 track. | Plays through default audio output. Transport bar shows position. | ☐ | ☐ |
| C2 | Adjust volume slider. | Volume changes audibly. | ☐ | ☐ |
| C3 | Open Equalizer dialog, drag sliders. | Audible EQ effect on output. | ☐ | ☐ |
| C4 | Toggle EQ off / on. | Audio audibly returns to flat / EQ'd. | ☐ | ☐ |
| C5 | Enable crossfade (Settings → Playback). | Track changes overlap by configured seconds. | ☐ | ☐ |
| C6 | Disable crossfade, enable gapless. | Album-cut tracks transition without a gap. | ☐ | ☐ |
| C7 | Shuffle + skip 5 tracks. | New track plays each time; no crash. | ☐ | ☐ |

## D. Library

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| D1 | Drag a folder of audio files into the library tab. | Folder added; scan starts; tracks appear. | ☐ | ☐ |
| D2 | Type a search term in the search box. | Results filter; clear-button works. | ☐ | ☐ |
| D3 | Rate a track 4 stars. | Rating persists after reopening track. | ☐ | ☐ |
| D4 | Right-click → Edit metadata. | Dialog opens; edit a title and save. | ☐ | ☐ |
| D5 | Create a smart playlist (e.g. "rated >= 4 stars"). | Playlist appears in sidebar; matching tracks visible. | ☐ | ☐ |
| D6 | Run duplicate finder. | Reports duplicates without deleting files. | ☐ | ☐ |

## E. CD detection + ripping  *(requires a real audio CD)*

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| E1 | Insert an audio CD. | "Disc" tab populates; tracks listed. | ☐ | ☐ |
| E2 | Right-click → Look up metadata. | CTDB / MusicBrainz returns title + artist + tracks. | ☐ | ☐ |
| E3 | Switch to "Rip" tab; choose FLAC; start rip. | Progress bar advances; per-track files created. | ☐ | ☐ |
| E4 | Rip completes. | Files imported into library; CD ejects (if "eject after rip" enabled). | ☐ | ☐ |
| E5 | Verify ripped FLAC file plays back identically to the source. | Sounds correct. | ☐ | ☐ |

## F. Video player

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| F1 | Open a local MP4 in the Video tab. | Plays; transport responsive. | ☐ | ☐ |
| F2 | Press fullscreen. | Enters fullscreen; OSD visible briefly. | ☐ | ☐ |
| F3 | Press Esc. | Returns to windowed; previous size restored. | ☐ | ☐ |
| F4 | Take a snapshot. | PNG saved to configured snapshot folder. | ☐ | ☐ |
| F5 | Load external subtitle file. | Subtitles render. | ☐ | ☐ |

## G. YouTube  *(requires internet)*

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| G1 | Switch to YouTube tab for the first time. | **Acknowledgement dialog appears.** | ☐ | ☐ |
| G2 | Cancel the dialog. | Tab reverts to previous selection. No YouTube view instantiated. | ☐ | ☐ |
| G3 | Switch again; check the box; accept. | Setting persists; tab now opens. | ☐ | ☐ |
| G4 | Search for a known song. | Result list with thumbnails appears within ~10s. | ☐ | ☐ |
| G5 | Download audio (FLAC). | Progress log advances; file lands in YouTube folder; library imports it. | ☐ | ☐ |
| G6 | Download video (MP4 1080p). | Same; video appears in Video tab catalog. | ☐ | ☐ |

## H. Podcasts + radio

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| H1 | Subscribe to a public podcast feed. | Feed adds; episode list populates. | ☐ | ☐ |
| H2 | Play an episode. | Plays through libVLC; transport correct. | ☐ | ☐ |
| H3 | Add an internet radio station via M3U. | Stream plays. | ☐ | ☐ |

## I. DLNA cast + server  *(requires a real DLNA renderer on the LAN)*

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| I1 | Click Cast toolbar button while a track is playing. | Renderer list populates. | ☐ | ☐ |
| I2 | Pick a renderer. | Renderer starts playing; local playback pauses. | ☐ | ☐ |
| I3 | Skip next track. | Renderer follows. | ☐ | ☐ |
| I4 | Stop cast. | Renderer stops; local playback can resume. | ☐ | ☐ |
| I5 | Enable DLNA server (Settings → DLNA). | Other LAN devices can browse Sea Lyon's library. | ☐ | ☐ |

## J. Auto-update

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| J1 | Help → Check for Updates… | Toast "You're running the latest version" appears (manual check fires worker). | ☐ | ☐ |
| J2 | Settings → Updates. | Toggle on; URL populated; "Last checked: ..." reflects J1. | ☐ | ☐ |
| J3 | Override the appcast URL to a fake one with version X.Y.Z+1. | Manual check shows UpdateAvailableDialog with release notes. | ☐ | ☐ |
| J4 | Click "Download Now". | Default browser opens to the enclosure URL. | ☐ | ☐ |
| J5 | Re-trigger; click "Skip This Version". | "Stop skipping" link appears in Settings → Updates. | ☐ | ☐ |

## K. Diagnostics & support

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| K1 | Help → Open Log Folder. | Explorer opens to `%APPDATA%\LyonMusicManager\logs`. | ☐ | ☐ |
| K2 | Help → Copy Diagnostics to Clipboard. | Toast confirms; paste shows multi-section bundle. | ☐ | ☐ |
| K3 | Inspect the bundle. | `lastfm_session_key`, `listenbrainz_token`, `theaudiodb_api_key` all `<redacted>`. Library paths visible. | ☐ | ☐ |
| K4 | Help → Runtime Diagnostics. | All checks ✅ on a normal Windows machine. | ☐ | ☐ |
| K5 | Help → About → System Info. | Log folder path is correct; "Open" button works. | ☐ | ☐ |
| K6 | About → Acknowledgements → Open Privacy Policy. | PRIVACY.md opens in default app. | ☐ | ☐ |
| K7 | About → Licenses. | Full THIRD_PARTY_NOTICES.txt visible in scroll area. | ☐ | ☐ |

## L. Uninstall

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| L1 | Settings → Apps → Uninstall Sea Lyon Media Manager. | Standard uninstaller runs. | ☐ | ☐ |
| L2 | Uninstaller asks "Also remove your library, settings, and cache?". | Yes / No prompt appears. | ☐ | ☐ |
| L3 | Choose **No**. | App folder removed; `%APPDATA%\LyonMusicManager\` intact. | ☐ | ☐ |
| L4 | Reinstall; data preserved. | First-run wizard does NOT appear (settings retained). | ☐ | ☐ |
| L5 | Uninstall again; choose **Yes**. | `%APPDATA%\LyonMusicManager\` removed. | ☐ | ☐ |
| L6 | Reinstall; clean state. | First-run wizard appears. YouTube ack re-required. SmartScreen toast appears once. | ☐ | ☐ |

## M. HiDPI / display matrix

See [`HIDPI_MATRIX.md`](HIDPI_MATRIX.md) for the full matrix. Spot-check at
minimum:

| # | Configuration | Expected | Win10 | Win11 |
|--|--|--|--|--|
| M1 | 1920×1080 @ 100% scale. | Crisp; no clipping. | ☐ | ☐ |
| M2 | 2560×1440 @ 125% scale. | Layout correct. | ☐ | ☐ |
| M3 | 3840×2160 @ 150% scale. | All icons + text scale; no widget overflow. | ☐ | ☐ |
| M4 | 3840×2160 @ 200% scale (4K, default Win11 scale). | Crisp; transport readable. | ☐ | ☐ |

## N. Stress / soak

| # | Step | Expected | Win10 | Win11 |
|--|--|--|--|--|
| N1 | Queue 50 tracks, enable shuffle + repeat all, play through. | No crash; transport stays responsive. | ☐ | ☐ |
| N2 | 30-minute crossfade soak (auto-skip every ~10s). | No memory growth >100 MB; no audio dropouts. | ☐ | ☐ |
| N3 | Library scan of a 10k-track folder. | Completes; UI remains responsive; library count matches. | ☐ | ☐ |

---

## Sign-off

- [ ] Section A (Installer) green on Win10
- [ ] Section A green on Win11
- [ ] All required sections (B, C, D, J, K, L) green on Win10
- [ ] All required sections green on Win11
- [ ] Optional sections (E, F, G, H, I, M, N) at least attempted on one VM
- [ ] All failures filed as `release-blocker` issues and resolved

**Approved for publish:** _signed name & date_
