# Sea Lyon Media Manager — Code Review & Security Audit

| | |
|---|---|
| **Project** | Sea Lyon Media Manager |
| **Version reviewed** | `0.9.0-rc2` (branch `LMM-DEV`) — targeting `1.0.0` |
| **Date** | 2026-05-29 |
| **Scope** | Full source tree (`lyon/core`, `lyon/ui`, `scripts`, `build`, CI workflows) — ~144 Python files, ~30k LOC |
| **Type** | Read-only review: correctness bugs, code quality, full security audit |
| **Method** | 5 specialized review agents (parallel) + lead-reviewer verification of all High-severity and selected findings against source |
| **Code changes** | **None** — this engagement produced findings only; no source was modified |

> **About this report.** Findings were produced by a team of five specialized AI review agents, each scoped to a coherent slice of the codebase (network/servers, local-execution/supply-chain, data layer, playback/UI bugs, and code quality). Every High-severity finding — and a representative sample of the rest — was independently re-verified against the actual source by the lead reviewer; verified items are marked **✓ Verified**. Confidence levels are stated per finding. Severities reflect realistic impact for a **locally-installed desktop application** on a home / small-office LAN, not a public web service.

---

## 1. Executive summary

Sea Lyon is a mature, well-structured desktop media manager, and the audit found **no critical, remotely-exploitable vulnerabilities**. The security posture is notably *better* than typical for this class of app: every untrusted XML/RSS/SOAP parse uses `defusedxml`, there is **no `verify=False`** anywhere, there is **no `shell=True`** anywhere (all subprocess calls pass argument lists), the DLNA file server is **not path-traversable** (files are located by integer DB id and confirmed to live under a library root), and secrets are externalized rather than committed.

The work that matters before the 1.0 ship falls into three buckets:

1. **A real, user-visible playback bug cluster.** The gapless-playback prebuffer is **not cancelled on `seek()` or `pause()`** ([player.py](lyon/core/player.py)), so a stale second audio stream can be promoted at the wrong moment — exactly the "wrong track / double audio" class of symptom the recent `fix playback` / `Fix Gapless Playback` commits have been chasing. **✓ Verified.**

2. **Two "remove before release" hygiene items.** A `# TEMP DIAG` instrumentation block is still **live in the hottest scan path** ([library.py:1643-1660](lyon/core/library.py:1643)) — it imports three modules per call, leaks an unbounded dict, and logs stack traces at WARNING during normal scans. And ~15 `except Exception: pass` handlers swallow failures with no log, making field bugs invisible. **✓ Verified (TEMP DIAG).**

3. **Defense-in-depth security hardening,** none of it remotely critical but all worth closing for a public 1.0: the DLNA server defaults to binding `0.0.0.0` with only coarse "any private IP" access control; several code paths fetch user/feed-supplied URLs without SSRF guards; untrusted CUE/M3U/PLS files are parsed with no size cap (local DoS) and a CUE `FILE` directive can reference paths outside the library; and the auto-update path verifies no cryptographic signature (mitigated today because the updater only *opens the download in a browser* — it does not auto-install).

The codebase's biggest maintainability liabilities are a few God-sized constructors (`LibraryView.__init__` 328 lines, `MainWindow.__init__` 277 lines) and silent error handling. Overall: **solid foundation, a short and clear punch-list to reach 1.0 quality.**

---

## 2. Severity summary

| Severity | Security | Bugs | Code Quality | Total |
|---|---|---|---|---|
| **Critical** | 0 | 0 | 0 | **0** |
| **High** | 0 | 2 | 2 | **4** |
| **Medium** | 8 | 6 | 6 | **20** |
| **Low** | 9 | 9 | 5 | **23** |
| **Info** | 5 | 1 | 2 | **8** |
| **Total** | **22** | **18** | **15** | **55** |

*The `_read_tags` TEMP-DIAG block was flagged independently by two agents (as DATA-06 and QUAL-02); it is counted once, under Code Quality. The CTDB-over-HTTP item is excluded from counts per the engagement scope (see §7).*

---

## 3. Methodology & scope

**In scope (reviewed):** the full `lyon/` package (core engine + Qt UI), `scripts/` (build/sign/notarize/fetch-vendor-binaries), `build/` (PyInstaller spec, Inno Setup, entitlements), GitHub Actions workflows, and the dependency manifests (`requirements*.txt`, `pyproject.toml`).

**Five specialized agents:**
- **SEC-NET** — DLNA/UPnP server, SSDP discovery, Chromecast/AVTransport casting, remote metadata clients, podcast/radio feeds, scrobbler.
- **SEC-EXEC** — subprocess/exec surface, yt-dlp, ripper, auto-updater, secret storage, diagnostics, supply chain / dependency pins, build & signing.
- **DATA** — SQLite library, smart-playlist rule→SQL, tag writing, CUE/M3U/PLS parsing, filesystem watcher.
- **BUG** — playback state machine (gapless/crossfade), libVLC backend, and core UI threading/lifecycle.
- **QUAL** — maintainability across the tree, with emphasis on the largest UI files and error-handling patterns.

**Lead-reviewer verification.** Independent ground-truth scans confirmed the cross-cutting security claims (`shell=True`, `verify=False`, XML parsing, network binding, SQL construction, updater integrity keywords, secrets), and the source for every High finding plus selected Mediums was read directly. Verified items are marked **✓ Verified**.

**Limitations.** This is a static, read-only review; no code was executed against a live disc/network/renderer. Dependency-CVE assessment was reasoned from version strings (no live CVE database), so those items carry explicit confidence caveats.

---

## 4. Security audit

### 4.1 Network exposure & DLNA server

#### SEC-NET-01 — DLNA server binds to `0.0.0.0` by default with only coarse IP-range access control · **Medium** · ✓ Verified
- **Location:** [settings.py:311,358](lyon/core/settings.py:311); [dlna_server.py:108-114,1154-1159](lyon/core/dlna_server.py:1154)
- **Confidence:** High
- **Description:** `dlna_bind_address` defaults to `"0.0.0.0"` and the only gate is `_is_allowed_client`, which returns true for **any** loopback, RFC-1918 private, *or* link-local source. There is no per-device pairing, token, or user confirmation. (The gate *is* correctly enforced on all of `do_GET`/`do_HEAD`/`do_POST` and on SSDP M-SEARCH responses — the issue is the breadth of "allowed," not a missing check.)
- **Impact:** When DLNA sharing is enabled, any host on the same LAN/VLAN (coffee shop, dorm, office guest Wi-Fi, a compromised IoT device) can enumerate and stream the user's entire audio/video library unauthenticated. This is the highest-impact security item because it exposes file *content*.
- **Recommendation:** Keep DLNA off until explicitly enabled (confirm this is the default). When enabled, prefer binding the specific active LAN interface over `0.0.0.0`; consider restricting to the server's own subnet rather than all private ranges; drop `is_link_local` from the allowlist (never a legitimate DLNA client); and surface the LAN-exposure clearly in the settings UI. A lightweight first-seen-client confirmation would materially raise the bar.

### 4.2 SSRF & remote-data fetching

#### SEC-NET-02 — SSRF: app fetches user/feed/discovery-supplied URLs with no host restriction · **Medium**
- **Location:** [dlna_renderer_discovery.py:123-160](lyon/core/dlna_renderer_discovery.py:123) (`_fetch_device`); [radio.py:138-173](lyon/core/radio.py:138) (`check_station_health`); [podcast.py:88-99](lyon/core/podcast.py:88) (`fetch_feed`); [metadata.py:1053-1088](lyon/core/metadata.py:1053) (`_fetch_artwork_url`)
- **Confidence:** Medium
- **Description:** Several paths issue outbound requests to URLs originating from untrusted input, with no allow/deny check on the resolved host and with default redirect-following: SSDP `LOCATION` (attacker-controllable by anyone on the LAN), saved/imported radio station URLs, podcast/OPML feed URLs, and `artwork_url` values pulled from remote metadata. All will happily connect to `http://127.0.0.1/...`, `http://169.254.169.254/...`, or other internal hosts, and follow 3xx redirects inward.
- **Impact:** Turns the user's machine into a request proxy onto its own trusted LAN — probing internal services (routers, NAS/printer admin panels, localhost daemons) and potentially triggering state-changing GETs on CSRF-weak embedded devices. Mostly blind (no response reflection, no credentials attached), hence Medium.
- **Recommendation:** Before fetching, resolve the host and reject loopback/private/link-local/internal targets, **re-validating after each redirect** (or disable auto-redirects and validate manually) to defeat DNS-rebind / redirect bypass. Apply uniformly across the four sites. Also bound the size of the renderer description XML in `_fetch_device` (today `resp.content` is read with no cap, unlike the 10 MB-capped podcast path).

#### SEC-NET-03 — Cast/AVTransport SOAP sent to unvalidated renderer control URLs (SSDP spoofing) · **Low**
- **Location:** [cast_controller.py:530-552](lyon/core/cast_controller.py:530); URL flows from [dlna_renderer_discovery.py:142-149](lyon/core/dlna_renderer_discovery.py:142)
- **Confidence:** Medium
- **Description:** `av_transport_url` derives from an unauthenticated SSDP `LOCATION`; the cast worker POSTs SOAP (`SetAVTransportURI`/`Play`) to it with no check it points at a real, user-intended renderer. A LAN attacker answering the `MediaRenderer` M-SEARCH can register a fake device; if the user selects it, the app sends SOAP POSTs (containing the local media URL) to an attacker-chosen host.
- **Impact:** Constrained, user-initiated request forgery — attacker must be on-LAN and the user must pick the impostor. Leaks the local DLNA media URL (already LAN-reachable per SEC-NET-01); no credentials sent.
- **Recommendation:** Validate the control URL resolves to a private/LAN address (reuse the SEC-NET-02 guard), ideally same-subnet; show the renderer's resolved host/IP in the picker so users can spot impostors.

#### SEC-NET-04 — `cast_controller._didl` double-escapes already-escaped values · **Low**
- **Location:** [cast_controller.py:504-527](lyon/core/cast_controller.py:504) (`_didl`), called from `:227-237`, `:427-437`
- **Confidence:** High
- **Description:** `_didl()` already XML-escapes each field and returns a full DIDL-Lite document; callers then `escape(_didl(...))` the entire document again. Meanwhile `_soap()` interpolates arg values raw (`f"<{k}>{v}</{k}>"`), which is *why* callers pre-escape. The escaping responsibility is split inconsistently.
- **Impact:** Not injection (values are over-escaped, if anything) — a robustness/correctness issue: titles with `&`/`<`/quotes/non-ASCII may render wrong or be rejected by strict renderers. Flagged because a future `_soap` arg added without manual escaping would inject into the SOAP body.
- **Recommendation:** Centralize escaping in `_soap()` (escape each value exactly once) and stop pre-escaping at call sites, or have `_didl` return an unescaped inner fragment — either way, escape every SOAP value exactly once so new args are safe by default.

#### SEC-NET-05 — DLNA `friendlyName` reflected into the discovery/description surface · **Low (Info)**
- **Location:** [dlna_server.py:141,147](lyon/core/dlna_server.py:141)
- **Confidence:** High
- **Description:** The user-configured friendly name is embedded in the device description, **correctly escaped** via `escape()`. The only note is defense-in-depth: it is broadcast on the LAN to arbitrary third-party control points, with no length bound.
- **Recommendation:** Bound the friendly-name length and optionally restrict the character set when persisting. No change needed to the (correct) escaping.

### 4.3 Update & distribution integrity

#### SEC-EXEC-01 — No signature verification of update artifacts; Windows installer unsigned · **Medium** · ✓ Verified
- **Location:** [updater.py](lyon/core/updater.py) (whole module; docstring line 13 states *"signatures omitted for the v1.0 unsigned ship"*); [update_dialog.py:97-101](lyon/ui/update_dialog.py:97); `.github/workflows/windows-build.yml` (no `signtool`)
- **Confidence:** High
- **Description:** The updater is, by deliberate design, a **notifier only** — it fetches the appcast over HTTPS (GitHub Pages), parses it with `defusedxml`, and on "Download" hands the enclosure URL to the OS browser (`QDesktopServices.openUrl`). It does **not** download or apply anything in-place. There is no `edSignature`/asymmetric signature on the feed, the app verifies no SHA-256 of the artifact, and the Windows installer has **no Authenticode signature** at all.
- **Impact:** Because the user must manually run the downloaded installer (and macOS Gatekeeper still checks notarization for signed builds), this is **not** a silent-RCE auto-update channel — hence Medium, not Critical. The residual risk is that nothing cryptographically ties the downloaded bytes to the publisher; a compromised release host or TLS path could serve a malicious installer, and the Windows side has no signature for users to trust.
- **Recommendation:** For 1.0, Authenticode-sign the Windows installer + main `.exe`, and surface the published SHA-256 in the download dialog for out-of-band verification. **Before ever adding an in-place auto-updater**, require an asymmetric signature (e.g. Sparkle `edSignature`/EdDSA) verified against a public key compiled into the app — not a hash fetched from the same server. Keep the browser-handoff model until then. *(The unsigned 1.0 installer is a documented shipping decision — see §7.)*

#### SEC-EXEC-02 — Update download URL opened with no scheme allow-list · **Low**
- **Location:** [update_dialog.py:97-101](lyon/ui/update_dialog.py:97)
- **Confidence:** High
- **Description:** `download_url`/`release_url` come straight from the appcast and are passed to `QDesktopServices.openUrl(QUrl(target))` with no check that the scheme is http/https. A compromised appcast could supply a `file:`/`smb:`/handler-triggering scheme.
- **Recommendation:** Validate the parsed scheme is `https` (or `http`) with a non-empty host before `openUrl`; reuse the existing `urlparse`-based stream-URL validation.

#### SEC-EXEC-09 — `update_appcast_url` user/registry-settable without HTTPS enforcement · **Low**
- **Location:** [settings.py:321-323,365-367](lyon/core/settings.py:321); Settings dialog [settings_dialog.py:534](lyon/ui/settings_dialog.py:534); written to `HKCU\...\AppcastUrl` by [build/lyon.iss:103-105](build/lyon.iss:103)
- **Confidence:** High
- **Description:** The appcast URL defaults to the project HTTPS Pages URL but is freely editable and (on Windows) stored in an unprivileged-writable HKCU value; `__post_init__` only strips/defaults it, never requiring `https`.
- **Impact:** Local-write prerequisite (not a remote vector), but combined with SEC-EXEC-02 it lets local tampering point "updates" at an arbitrary host whose enclosure URL is then opened.
- **Recommendation:** Enforce `https://` for `update_appcast_url` in `__post_init__`, falling back to the default otherwise — mirroring the existing stream-URL validation.

### 4.4 Secrets & supply chain

#### SEC-EXEC-03 — Shared Last.fm API key + secret baked into every distributed build · **Medium**
- **Location:** CI writes `lyon/core/_secrets.py` (`.github/workflows/windows-build.yml:238`, `macos-build.yml:81`); consumed at [scrobbler.py:24-28,67](lyon/core/scrobbler.py:24)
- **Confidence:** High
- **Description:** `_secrets.py` (git-ignored, **not** committed — confirmed) is generated at build time with the Last.fm key/secret and used to compute the API signature. The intrinsic issue: an *application* secret shipped inside a client binary is trivially recoverable (plaintext Python in the bundle).
- **Impact:** The Last.fm API *secret* (not a user credential) is extractable from any install; an attacker can impersonate the app's API identity to Last.fm (forge signatures, get the app's key throttled/banned). Standard "client secret in a distributed app" problem; does not expose per-user session keys.
- **Recommendation:** Treat the secret as effectively public in your threat model. If signature integrity matters, proxy Last.fm signing through a small server-side endpoint so the secret never ships; at minimum keep it rotatable and monitor for abuse.

#### SEC-EXEC-04 — VLC DMG checksum verification is conditional / skippable (macOS) · **Medium**
- **Location:** [scripts/fetch-macos-vendor-binaries.sh:99-113](scripts/fetch-macos-vendor-binaries.sh:99) (and the early-return at lines 22-24)
- **Confidence:** High
- **Description:** ffmpeg/fpcalc/libdiscid are pinned to hardcoded SHA-256s, but the **VLC DMG is not**: it's downloaded, then a sidecar `.sha256` is fetched *best-effort* and only compared if that fetch succeeds — otherwise the build proceeds with an **unverified** DMG. Separately, `verify_checksum()` returns success when the expected hash is empty, silently disabling verification if a `*_SHA256` var is blank. No `VLC_*_SHA256` is pinned in CI.
- **Impact:** A compromised/MITM'd VLC mirror (or a missing sidecar) folds an unverified `libvlc.dylib` + plugins into the app — which is then code-signed by *this* project, inheriting its trust. The Windows build *does* pin+verify VLC; the macOS path is the gap.
- **Recommendation:** Pin a known-good `VLC_*_SHA256` and make the macOS VLC download **fail closed** on absent/mismatched checksum, exactly like ffmpeg/libdiscid. Make `verify_checksum` treat an empty expected hash as a hard error in release builds.

#### SEC-EXEC-05 — fpcalc (Windows) downloaded without SHA-256 verification · **Low**
- **Location:** [scripts/build-windows.ps1:256-271](scripts/build-windows.ps1:256)
- **Confidence:** High
- **Description:** In the local PowerShell build, ffmpeg/libdiscid/VLC use `Invoke-VerifiedDownload`, but fpcalc uses a bare `Invoke-WebRequest` + a version-string assertion only — no content hash. (The GitHub Actions path appears stricter; this affects manual/local builds.)
- **Impact:** A tampered `fpcalc.exe` reporting the expected version would be bundled and is invoked as a subprocess by the app. Low (requires compromising the Chromaprint release host; local builds only) but inconsistent with the otherwise verify-everything pattern.
- **Recommendation:** Pin fpcalc's SHA-256 and route it through `Invoke-VerifiedDownload`; keep the version assertion as a secondary check.

#### SEC-EXEC-06 — Signing cert written to predictable world-readable `/tmp/cert.p12` in CI · **Low**
- **Location:** [scripts/import-codesign-cert.sh:9](scripts/import-codesign-cert.sh:9)
- **Confidence:** Medium
- **Description:** The Developer ID `.p12` is base64-decoded to a fixed `/tmp/cert.p12`, imported, then `rm -f`'d. `/tmp` is world-readable with a predictable name, creating a brief read/symlink-race window.
- **Impact:** On a shared/persistent runner, the signing cert (password also in env) could be exfiltrated during the import window. Largely theoretical on ephemeral GitHub-hosted runners.
- **Recommendation:** Use a `mktemp` file with `umask 077` (or `install -m 600`), prefer importing without persisting to disk where possible, and keep `trap`-based cleanup.

#### SEC-EXEC-07 — API keys/tokens stored plaintext in `settings.json` · **Low**
- **Location:** [settings.py:271,302-306,486-493,528-533](lyon/core/settings.py:486)
- **Confidence:** High
- **Description:** `theaudiodb_api_key`, `lastfm_session_key`, `listenbrainz_token` are persisted as plaintext JSON. Mitigation: atomic write + `chmod 0o600` — but `chmod` is effectively a no-op for confidentiality on Windows (NTFS ACLs), a primary target.
- **Impact:** Any process running as the user (or anyone with read access on a shared Windows box) can read these revocable, low-privilege scrobbling tokens. Diagnostics correctly redacts them (SEC-EXEC-11).
- **Recommendation:** Acceptable for 1.0 given low value; document in PRIVACY.md. To harden, store secrets via the OS keychain/credential locker (`keyring`) and keep `chmod` for the non-secret remainder.

#### SEC-EXEC-12 — Dependency pin review · **Info**
- **Confidence:** Medium (reasoned from version strings; no live CVE DB)
- All pins are exact `==` (good); nothing resembles a typosquat. Action items:

| Package (pin) | Note |
|---|---|
| `requests==2.34.2` | Version is **ahead of** the releases in the reviewer's knowledge (which top out ~2.32.x) — either post-cutoff or a mis-pin. **Confirm it resolves to a real, non-yanked PyPI release.** |
| `yt-dlp==2026.3.17` | Ships frequent security/extractor fixes against hostile remote data; a date pin goes stale fast. **Establish a refresh cadence.** |
| `python-vlc==3.0.21203` / bundled VLC 3.0.21 | libVLC has a steady stream of demuxer/decoder CVEs; runtime is bundled. **Track VLC security releases.** |
| `Pillow==12.2.0` | Processes artwork/thumbnails; periodic decoder CVEs — keep current. |
| `defusedxml==0.7.1` | Correct choice for the XML attack surface. Good. |

### 4.5 Untrusted-file parsing (data-layer security)

#### DATA-01 — Unparameterized `LIMIT` interpolation in smart-playlist SQL · **Medium** · ✓ Verified
- **Location:** [smart_playlist.py:150](lyon/core/smart_playlist.py:150); consumed at [library.py:1372-1377](lyon/core/library.py:1372)
- **Confidence:** High
- **Description:** `limit = f"LIMIT {spec.limit}"` is interpolated raw. The `WHERE` clause is fully parameterized and `order_by` is allowlisted (`_ORDER_BY_COLS`), but the limit value is concatenated. It is *currently* safe only because `spec.limit` passes through `int()` in `spec_from_json`. Smart-playlist rules are persisted as JSON in `playlists.rules` and recompiled on every view, so a hand-edited/corrupted rules blob is an attacker-controllable input in the local threat model.
- **Impact:** The one place a *value* (not a server-defined identifier) is concatenated into SQL. Neutralized by an upstream coercion rather than by the query construction — fragile against any future caller that builds a `SmartPlaylistSpec` directly.
- **Recommendation:** Bind the limit as a parameter (`LIMIT ?`). Keep the allowlist for column/direction (those can't be parameterized in SQLite). Optionally assert `isinstance(spec.limit, int)` at the compile boundary.

#### DATA-02 — No size cap on untrusted CUE/M3U/PLS reads (local memory exhaustion) · **Medium**
- **Location:** [cue_parser.py:54-57](lyon/core/cue_parser.py:54); [playlist_import.py:40-42,56-58](lyon/core/playlist_import.py:40)
- **Confidence:** High
- **Description:** All three parsers `read_text()` the entire file with no length bound. A `.cue`/`.m3u`/`.pls` is fully attacker-controllable (dropped into a watched folder, or chosen via import). A multi-GB file — or a CUE with millions of `TRACK` lines, which amplifies into millions of SQL UPSERTs inside one lock-held loop — exhausts memory/CPU.
- **Impact:** DoS via memory/CPU exhaustion and scanner/UI stalls; triggerable in the watched-folder flow with no explicit user action.
- **Recommendation:** Stat the file and refuse to parse beyond a sane ceiling (a few MB for these line-oriented formats); cap the number of parsed entries; stream line-by-line rather than reading the whole blob.

#### DATA-03 — CUE `FILE` target resolved & indexed without path containment · **Medium**
- **Location:** [cue_parser.py:98-106](lyon/core/cue_parser.py:98); consumed at [library.py:562,598](lyon/core/library.py:562)
- **Confidence:** Medium
- **Description:** The CUE `FILE "..."` directive is honored verbatim, including absolute paths and `..` traversal, with no check that the resolved path stays under the CUE's directory or a library root. The resolved path is probed by Mutagen and stored as `cue_image_path`, which later becomes the **playback URI** for the virtual tracks.
- **Impact:** Path traversal / arbitrary-file reference — a malicious CUE in a watched folder can make the app open and persist an arbitrary path (e.g. `../../../../etc/passwd`) as a playable item. Bounded (local files the user can already read; Mutagen usually fails on non-media), so primarily an unexpected-file-access surface.
- **Recommendation:** After `resolve()`, verify the target is contained within the CUE's parent directory (or a known library root); reject absolute paths and any path that escapes the base.

#### DATA-10 — M3U/PLS `_normalize` mishandles UNC `\\host\share` / `file://` URIs · **Low**
- **Location:** [playlist_import.py:19-34](lyon/core/playlist_import.py:19)
- **Confidence:** Low
- **Description:** The `startswith("//")` carve-out falls through to `Path(entry).resolve()`, which on a UNC path triggers network access during `resolve()`, and `file://` URIs are treated as relative filenames. No containment check; entries are only *matched* against the library (not opened), limiting real impact.
- **Recommendation:** Explicitly handle/strip `file://`, set a policy for UNC (timeout or skip), and avoid `resolve()` (which touches the FS/network) when a string match is all that's needed — `os.path.normpath(os.path.abspath(...))` suffices.

---

## 5. Correctness bugs

### 5.1 Playback engine (gapless / crossfade) — the high-severity cluster

> This cluster aligns with the active `fix playback` / `Fix Gapless Playback` commit churn. The root pattern: cancellation of the gapless prebuffer is wired into `stop()`/`cleanup()` but **not** into `seek()`/`pause()`, and the prebuffer is promoted without re-validating against the live queue state.

#### BUG-01 — Gapless prebuffer not cancelled on `seek()` → stale prebuffer promoted mid-track · **High** · ✓ Verified
- **Location:** [player.py:345-347](lyon/core/player.py:345) (`seek`), `:814-832` (`_maybe_gapless_prebuffer`), `:860-886` (`_promote_gapless_prebuffer`)
- **Confidence:** High
- **Description:** Near end-of-track, a second backend is pre-rolled for the next track and stored in `_gapless_prebuffer_backend`. `seek()` calls only `_cancel_crossfade()` — **not** `_cancel_gapless_prebuffer()` (which `stop()`/`cleanup()` do call, confirmed at [player.py:299-308](lyon/core/player.py:299)). Sequence: track at 0:58/1:00 arms the prebuffer; the user drags back to 0:10; the prebuffer stays armed against `idx+1`. When the rewound track later truly ends, `_promote_gapless_prebuffer` swaps in the pre-rolled track instead of re-evaluating repeat/advance logic, and trusts the arm-time index even if repeat mode / next index changed meanwhile.
- **Impact:** After seeking backward near the end of a track with gapless on, the wrong/stale next track plays, or a track meant to repeat is skipped. Intermittent and hard to reproduce — the signature of the recent playback churn.
- **Recommendation:** Cancel the gapless prebuffer in `seek()`/`set_position` (as `stop()` already does) and let it re-arm on subsequent position ticks; re-validate `_gapless_prebuffer_index` against the live `_next_index()` at promotion time.

#### BUG-02 — Gapless prebuffer survives `pause()`; a second stream is promoted while paused · **High** · ✓ Verified
- **Location:** [player.py:289-291](lyon/core/player.py:289) (`pause`); `:618-629` / `_advance_after_end`
- **Confidence:** Medium-High
- **Description:** `pause()` calls only `_cancel_crossfade()`. If the prebuffer was armed in the final ~2s and the user pauses, the muted prebuffer backend is held for the entire pause; the `_maybe_gapless_prebuffer` guard (`prebuffer is not None`) blocks re-arming, and on resume the end-of-track detection window may have passed, so the muted prebuffer (now stale) gets promoted.
- **Impact:** Pausing within the last ~2s of a track (gapless on) leaves a dangling second VLC output and can jump to the wrong next track or briefly double-output on resume; the second `Instance`/`MediaPlayer` is held for the pause duration.
- **Recommendation:** Cancel (or pause/tear down) the gapless prebuffer in `pause()` too, clearing the guard so it re-arms cleanly on resume.

#### BUG-03 — Double play-count increment on gapless track end · **Medium**
- **Location:** [player.py:618-629,860-886](lyon/core/player.py:618)
- **Confidence:** High
- **Description:** Play-count increment is split between `_on_track_ended` (outgoing track) and `_maybe_auto_crossfade` (crossfade path). The gapless boundary itself is single-count, but in interaction with BUG-01/BUG-02 a promoted *stale* prebuffer whose track equals the just-ended track (e.g. after a repeat-mode toggle) increments the same `track.id` twice.
- **Impact:** Inflated play counts in repeat/seek edge cases. Data-quality bug, not a crash.
- **Recommendation:** Centralize increment at a single transition point keyed on the *outgoing* track identity; guard against counting the same id twice when promotion replays an index.

#### BUG-04 — `_meta_dispatch` can fire after `set_source`, applying the old stream's ICY tags to the new media · **Medium**
- **Location:** [playback_backend.py:334-360,514-545,546-579](lyon/core/playback_backend.py:514)
- **Confidence:** Medium
- **Description:** `_on_meta_event` (VLC thread) marshals a single-shot `_meta_dispatch.start()` via `invokeMethod(QueuedConnection)`. A queued `start` already in the GUI event queue can run *after* `set_source` set `_current_media` to the new media, so `_emit_pending_metadata` reads meta off the new media; during rapid station switching VLC may still expose the previous title.
- **Impact:** Transient wrong ICY title/artist on the transport bar/Now Playing right after switching streams; self-corrects on the next real meta event.
- **Recommendation:** Tag each dispatch with the media generation/source it was scheduled for and ignore stale dispatches (capture `_current_media is media` identity at schedule time).

#### BUG-05 — `UnavailablePlaybackBackend.pause()` emits `"stopped"`; state machine desyncs · **Medium**
- **Location:** [playback_backend.py:224-225](lyon/core/playback_backend.py:224); [player.py:293-297](lyon/core/player.py:293)
- **Confidence:** Medium
- **Description:** The unavailable backend's `pause()` emits `state_changed("stopped")` rather than being a no-op; a direct `player.pause()` while playback is unavailable produces a spurious `"stopped"` transition, and the state-label semantics differ from the real backend (which emits `"paused"`).
- **Impact:** Minor UI state flicker / interface-contract violation when VLC is unavailable.
- **Recommendation:** Make `UnavailablePlaybackBackend.pause()` a no-op; rely on `play()` for the user-facing unavailable notification.

#### BUG-06 — Crossfade auto-trigger is re-entrant within the `position_changed` emission · **Medium**
- **Location:** [player.py:568-571,697-780](lyon/core/player.py:697)
- **Confidence:** Medium
- **Description:** `_on_position_changed` re-emits `position_changed` to the UI and then calls `_maybe_auto_crossfade`, which can reassign `self._backend` mid-callback. The guard (`_fade_timer is not None`) can be bypassed for a very short next track: the just-promoted backend immediately emits its own `position_changed`, and a second `_maybe_auto_crossfade` can pass the remaining-time check and then `_cancel_crossfade()` tears down the in-progress fade.
- **Impact:** Back-to-back tracks shorter than the crossfade length (crossfade enabled) can stack/abort fades → volume jumps or a dropped track.
- **Recommendation:** Defer the crossfade decision out of the synchronous re-emission (zero-delay single-shot) and gate on a "transition in progress" flag held until the fade fully completes, not just on `_fade_timer`.

#### BUG-10 — `set_replaygain` mutates the multiplier during an active crossfade · **Low**
- **Location:** [player.py:372-384,782-791](lyon/core/player.py:372)
- **Confidence:** Medium
- **Description:** Changing ReplayGain settings mid-fade reassigns `self._rg_multiplier` for the current track but only restores volume if no fade is active; the next `_on_fade_tick` then applies the new multiplier to the incoming stream mid-curve while the fade-out side is untouched.
- **Impact:** One-time volume jump on the incoming track if RG settings change during the brief crossfade window.
- **Recommendation:** Defer RG recomputation until any in-progress fade completes, or snapshot multipliers into the fade tick at fade start.

#### BUG-07 / BUG-08 / BUG-09 — Lower-confidence playback/UI edges · **Low**
- **BUG-07** ([player.py:326-344](lyon/core/player.py:326)): `previous()` uses backend position to decide "restart vs go back"; right after an auto-advance the fresh backend's position is ~0, and with an empty shuffle `_play_history` Previous can become a no-op even when a logical previous exists. *Confirm intended Previous semantics at a track boundary; consider elapsed wall-clock since track change.*
- **BUG-08** ([now_playing.py:644-657](lyon/ui/now_playing.py:644)): the lyrics worker reads `Track` string fields off-thread; benign today (streams excluded; `Track` is a plain dataclass) but a latent race if lyric fetch is ever enabled for streams. *Snapshot the needed strings into locals before starting the thread.*
- **BUG-09** ([video_player_view.py:866-914,1464-1486](lyon/ui/video_player_view.py:866)): the deep chain of deferred `singleShot` lambdas around VLC output handoff is currently guarded (`_player is None` + `generation` checks) but brittle — any new deferred callback that forgets a guard will crash with "wrapped C/C++ object deleted." *Maintenance hazard; keep the guards on every new deferred callback.*

### 5.2 Data layer / persistence

#### DATA-04 — `commit=False` worker writes flushed by unrelated commits on a shared connection · **Medium**
- **Location:** [library.py:684-808](lyon/core/library.py:684) (the `commit=False` writers); driver [library_watcher.py:199-266](lyon/core/library_watcher.py:199)
- **Confidence:** Medium
- **Description:** One `sqlite3.Connection` (`check_same_thread=False`) is shared between the UI thread and `LibraryIndexThread`. The watcher performs a long batch with `commit=False` and commits once at the end, but **any** concurrent UI-thread write (`update_rating`, `increment_play_count`, `create_playlist`, …) commits the worker's in-flight, half-applied batch as a side effect. The `RLock` serializes statements but does not scope a transaction to one logical batch.
- **Impact:** Loss of atomicity for batch operations — an interrupted folder-move can be partially persisted if the UI committed in between.
- **Recommendation:** Give the indexing thread its own `sqlite3` connection (WAL supports concurrent readers + one writer), or wrap each logical batch in explicit `BEGIN…COMMIT` and ensure nothing else commits the shared connection mid-batch. Per-thread connections are the cleaner fix.

#### DATA-05 — No `rollback()` anywhere; a failed multi-statement batch half-commits · **Medium**
- **Location:** all writers in [library.py](lyon/core/library.py); exception handler [library_watcher.py:265-268](lyon/core/library_watcher.py:265)
- **Confidence:** High
- **Description:** There is no `conn.rollback()` anywhere in `lyon/core/`. Multi-statement methods (`_index_cue_file`, `move_paths_under`, playlist reorder, the worker `run()` loop) have no error path discarding partial work; the worker catches `Exception` and emits failure but leaves partial statements pending, to be committed by the next caller's `commit()` (see DATA-04).
- **Impact:** On any mid-batch failure the DB can be left partially mutated instead of all-or-nothing; combined with DATA-04 the partial state can become durable.
- **Recommendation:** Add `except: conn.rollback(); raise` (or `try/finally` transaction control) around multi-statement operations and roll back in the worker's failure handler. Pairs naturally with per-thread connections.

#### DATA-07 / DATA-08 / DATA-09 / DATA-11 / DATA-12 — Lower-severity data correctness · **Low**
- **DATA-07** ([library.py:1431-1444](lyon/core/library.py:1431)): `add_to_playlist` advances `position` even when `INSERT OR IGNORE` collides (sparse positions), and silently drops legitimately-repeated tracks from imported playlists. *Decide whether duplicates are allowed; only advance `pos` when `rowcount > 0`.*
- **DATA-08** ([library.py:548-557](lyon/core/library.py:548)): the CUE "unchanged" fast-path keys only on the `.cue` file's stat, so replacing the underlying **audio image** (same `.cue`) leaves stale durations/offsets. *Include the image file's stat/hash in the freshness check.*
- **DATA-09** ([library.py:562,569-575](lyon/core/library.py:569)): interior CUE tracks lacking `end_sectors` reuse the whole-image length as a duration fallback → wrong durations for malformed CUEs. *Apply the image-length fallback only to the genuine last track.*
- **DATA-11** ([library.py:317,343](lyon/core/library.py:317) vs [playlist_import.py:31-34](lyon/core/playlist_import.py:31)): indexing stores raw, un-normalized paths while matching uses `resolve()`/`normcase`; on case-insensitive FS or via symlinks this yields duplicate rows or missed updates/removals. *Choose one canonical form (`normcase(realpath(...))`) and apply it at the single ingress point and every lookup/removal.*
- **DATA-12** ([cue_parser.py:36,111-112](lyon/core/cue_parser.py:36)): a `TRACK` number matched by `\d+` with thousands of digits builds a huge int (used in `f"{cue}::{n}"`), feeding the DATA-02 amplification; otherwise crashes are caught broadly by the caller. *Bound the track number to 1–999.*

#### DATA-13 — `_compute_file_hash` uses MD5 + only 3×64KB samples → silent duplicate false-positives · **Info**
- **Location:** [library.py:1586-1610](lyon/core/library.py:1586)
- **Confidence:** Medium
- **Description:** Exact-dup detection hashes file size + three 64 KB windows; two distinct files sharing size and those windows collide and are reported as identical. (MD5 is fine for a non-security heuristic — the *partial sampling* is the risk.)
- **Impact:** The duplicate-finder may group non-identical files; if a UI flow bulk-deletes "duplicates," distinct content could be removed (the delete decision lives in the UI, out of this layer's scope).
- **Recommendation:** Treat the sampled hash as a *candidate* grouping and confirm with a full-content comparison before presenting/acting on "exact duplicate."

---

## 6. Code quality & maintainability

**Metrics:** bare `except:` = **0** (good); broad `except Exception` = **137** across 30+ files (~55 justified with `# noqa`/comment); **truly silent** (no log/feedback) ≈ **15** (QUAL-01); `print()` = 1 (intentional stderr fallback, `app.py:60`); TODO/FIXME/HACK = **0**; TEMP-instrumentation blocks = **1** (QUAL-02). **Largest files:** `library_view.py` (2362 L), `main_window.py` (1980 L), `library.py` (1735 L), `knowledge_base_dialog.py` (1704 L), `video_player_view.py` (1635 L). **Largest functions:** `LibraryView.__init__` (328 L), `MainWindow.__init__` (277 L), `Ripper.run` (180 L).

#### QUAL-02 / DATA-06 — TEMP diagnostic instrumentation live in `_read_tags` · **High** · ✓ Verified
- **Location:** [library.py:1643-1660](lyon/core/library.py:1643) *(flagged independently by the data and quality agents)*
- **Description:** A `# TEMP DIAG (LMM-DEV #4)` block sits in the hottest scan path: it `import`s `threading`/`time`/`traceback` **on every call**, writes to a module-global `_TAG_READ_TRACE` dict that is **never pruned** (unbounded growth proportional to library size), and emits a full stack trace at **WARNING** when a path is re-read within 5s (which happens during normal scans). This is shipping in the RC.
- **Impact:** Memory growth on large libraries, production log noise at WARNING, and per-file CPU overhead in the scan loop.
- **Recommendation:** **Remove the entire block (and `_TAG_READ_TRACE`) before 1.0.** Per project memory this instrumentation was always intended to be removed after the `#4` double-tag-read investigation concludes — make it the first pre-release cleanup.

#### QUAL-01 — Silent `except Exception: pass` in hot paths · **High**
- **Location (representative):** [now_playing.py:71,83,125,331](lyon/ui/now_playing.py:71); [library_view.py:527](lyon/ui/library_view.py:527); [replaygain.py:92,185](lyon/core/replaygain.py:92); [duplicate_dialog.py:382](lyon/ui/duplicate_dialog.py:382); [metadata_fetch_dialog.py:83](lyon/ui/metadata_fetch_dialog.py:83); [smart_playlist.py:101](lyon/core/smart_playlist.py:101); [video_player_view.py:919,925,931,1029](lyon/ui/video_player_view.py:919)
- **Description:** ~15 handlers catch all exceptions and `pass` with no log/counter/re-raise — failures in tag reading, lyric fetch, fingerprint scan, and corrupt-spec parsing leave no trace in the log file or UI.
- **Impact:** Field bugs become invisible; e.g. `smart_playlist.spec_from_json` swallowing a JSON error means silent data loss for a corrupted playlist.
- **Recommendation:** At minimum `LOG.debug(..., exc_info=True)` in every silent catch; promote corrupt-spec parsing to `LOG.warning`; surface a brief status update for user-triggered operations (lyrics, fingerprint scan).

#### QUAL-03 / QUAL-04 — God constructors · **Medium**
- `LibraryView.__init__` is **328 lines** ([library_view.py:542-869](lyon/ui/library_view.py:542)) and `MainWindow.__init__` is **277 lines** ([main_window.py:118-395](lyon/ui/main_window.py:118)), each building every sub-panel/service/signal inline — hard to test in isolation or navigate.
- **Recommendation:** Extract `_build_*()` factory methods + a `_connect_signals()` (the pattern `SettingsDialog` already uses well with per-tab `_build_*_tab()`), called from `__init__`.

#### QUAL-05 / QUAL-06 / QUAL-07 / QUAL-08 — Other Medium quality items
- **QUAL-05** ([main_window.py:554-633](lyon/ui/main_window.py:554)): `_ensure_tab_view` is an 8-branch `if name == ...` chain duplicating import→construct→connect→assign, implicitly coupled to `_TAB_ORDER`/`_tab_index`. *Replace with a `dict[str, Callable[[], QWidget]]` factory registry.*
- **QUAL-06** ([main_window.py:1298,1354](lyon/ui/main_window.py:1298)): `MainWindow` assigns `self._now_playing_view._settings = ...` directly — every other view has `apply_settings()`. *Add `NowPlayingView.apply_settings()` for a consistent contract.*
- **QUAL-07** (8 files; `ripper.py` 18×, `metadata.py`, `ctdb_verify.py`, …): `typing.Optional[X]` in a Py-3.14 codebase that otherwise uses `X | None`. *Normalize to `X | None`.*
- **QUAL-08** ([metadata.py:36-51](lyon/core/metadata.py:36)): ~8 module-level mutable singletons managed via scattered `global` statements; hard to test/reset. *Group into a single `_MetadataState` container.*

#### QUAL-09 – QUAL-15 — Low / Info quality items
- **QUAL-09** (Low): magic timer intervals (50/80/150/750/5000 ms) as bare literals across `main_window.py`, `library_view.py`, `player.py`, etc. *Name them as constants (the `_GAPLESS_PREBUFFER_MS = 2000` pattern).* 
- **QUAL-10** (Low): `Ripper.run` is 180 lines ([ripper.py:772-951](lyon/core/ripper.py:772)) — *extract `_fetch_artwork()`/`_read_toc_if_needed()`/`_rip_all_tracks()`/`_verify_and_log()`.*
- **QUAL-11** (Low): the ripper reports progress/errors only via a Qt `Signal(str)` to the UI ([ripper.py:758](lyon/core/ripper.py:758)) — failures leave no trace in the log file / diagnostics bundle. *Add parallel `LOG.info/warning` calls.*
- **QUAL-12** (Low): `_on_update_check_finished` uses `isinstance(info, UpdateInfo)` on a `Signal(object)` ([main_window.py:1707](lyon/ui/main_window.py:1707)) — loose signal typing. *Document the `UpdateInfo | None` contract.*
- **QUAL-13** (Low): thin tests — `test_disc_watcher.py` (1 assertion), no `write_replaygain` failure-path test, no test that the fingerprint scan continues after a per-track exception; limited `_SsdpResponder`/UPnP-event coverage. *Add error-path tests for the silent-catch areas.*
- **QUAL-14** (Info): `knowledge_base_dialog.py` is 1582 lines of inline HTML before the class ([knowledge_base_dialog.py:1](lyon/ui/knowledge_base_dialog.py:1)). *Move content to a `knowledge_base_content.py` module.*
- **QUAL-15** (Info): `MainWindow.closeEvent` repeats the "request stop → wait 3000ms → toast & ignore" block 5× ([main_window.py:1886-1940](lyon/ui/main_window.py:1886)). *Extract `_wait_for_thread(thread, label, timeout_ms)`.*

---

## 7. Explicitly out of scope / by-design

These were considered and deliberately **not** treated as vulnerabilities, per the engagement scope and documented project decisions:

- **CTDB (CUETools DB) over HTTP** — `http://db.cuetools.net/lookup2.php` ([metadata.py:22](lyon/core/metadata.py:22), [ctdb_verify.py:32](lyon/core/ctdb_verify.py:32)). The CTDB web service is **HTTP-only by design** (it offers no HTTPS endpoint), so this is **not** reported as a finding. Confirmed mitigations: no credentials are sent (only TOC layout + flags), the response is parsed with `defusedxml`, and it is used only to compare AccurateRip CRC integers — a tampered response can at worst flip an *advisory* rip-verification result, never execute code or write files.
- **Unsigned Windows 1.0 installer** — a documented shipping decision (README + `docs/SMARTSCREEN_NOTES.md`); SmartScreen warnings and SHA-256 manual verification are the stated mitigation. The *technical* recommendation to Authenticode-sign remains (SEC-EXEC-01), but shipping unsigned is an accepted business choice, not an oversight.

---

## 8. Strengths / good practices observed

The audit specifically confirmed a number of things done **right** — several are stronger than typical for this class of app:

- **No `verify=False` anywhere; no `shell=True` anywhere.** ✓ Verified. All HTTPS-capable services use HTTPS (MusicBrainz, Cover Art Archive, TheAudioDB, radio-browser.info, Last.fm, ListenBrainz); macOS cert issues are solved by loading `certifi` rather than disabling verification. Every subprocess call passes an **argument list**.
- **`defusedxml` for every untrusted XML/SOAP/RSS/OPML parse.** ✓ Verified — no stdlib `xml.etree`/`minidom`/`sax` touches untrusted data. XXE / billion-laughs mitigated across DLNA, casting, metadata, podcast, CTDB, and the updater.
- **DLNA file serving is not path-traversable.** Files are located by **integer DB id**, then `_resolved_path().resolve()` + `_path_is_under_roots()` confirm containment, and only regular files are served. Range parsing is bounded/validated (416 on bad ranges); SOAP bodies capped at 256 KiB; socket read timeout; the HTTP and SSDP paths are both gated by the client-allow check.
- **Strong untrusted-input path handling in the ripper/exec layer:** `safe_path_component` (control chars, reserved Windows device names) + `_assert_under_music_root`, single-drive-letter validation before eject (MCI-injection guard), and absolute paths for system tools.
- **Parameterized SQL throughout for values** (the smart-playlist `LIMIT` in DATA-01 is the lone exception); identifier interpolation is only ever from server-defined constants or hard allowlists; `LIKE` wildcards are escaped with `ESCAPE '\\'`. Clean versioned migrations; WAL + `busy_timeout` + `foreign_keys=ON`.
- **Correct Qt threading on the audio path:** VLC callbacks (on VLC threads) hop to the GUI thread via `QMetaObject.invokeMethod(QueuedConnection)` before touching widgets; backend swaps pair `_disconnect`/`_connect`; transient backends are torn down with `deleteLater()`; `closeEvent` drains worker threads before releasing native resources.
- **Secret hygiene:** secrets externalized (env / CI-injected, git-ignored `_secrets.py`), redacted from diagnostics, settings written atomically with `chmod 600`; the macOS pipeline does hardened-runtime codesign → notarize → staple and publishes a SHA256SUMS manifest with a draft release for human review.
- **Conservative updater** (notify-and-hand-to-browser) is the right posture until signed updates exist.
- **0 bare `except:`, 0 TODO/FIXME markers,** consistent `pathlib` usage, broad per-module test coverage (65 test files).

---

## 9. Prioritized remediation roadmap

### Must-fix before 1.0 (correctness & release hygiene)
1. **BUG-01 / BUG-02** — cancel the gapless prebuffer in `seek()` and `pause()` and re-validate the prebuffer index at promotion. *(High; user-visible playback bug.)* ✓ Verified
2. **QUAL-02 / DATA-06** — remove the `_read_tags` TEMP-DIAG block + `_TAG_READ_TRACE`. *(High; perf/memory/log noise shipping in the RC.)* ✓ Verified
3. **QUAL-01** — add logging to the ~15 silent `except: pass` handlers (especially `smart_playlist.spec_from_json`). *(High; observability.)*
4. **BUG-03** — de-duplicate the play-count increment path. *(Medium; data quality.)*

### Should-fix before 1.0 (security hardening)
5. **SEC-NET-01** — don't default-bind DLNA to `0.0.0.0`; tighten the access allowlist; surface LAN exposure in the UI.
6. **DATA-02 / DATA-03** — cap untrusted CUE/M3U/PLS size + entry counts; enforce CUE `FILE` path containment.
7. **DATA-01** — parameterize the smart-playlist `LIMIT`. ✓ Verified
8. **SEC-NET-02** — add an SSRF guard (reject internal hosts, re-validate on redirect) to the four fetch sites.
9. **SEC-EXEC-04** — pin + fail-closed the macOS VLC DMG checksum.
10. **SEC-EXEC-01 (partial)** — Authenticode-sign the Windows installer; show the SHA-256 in the update dialog. **SEC-EXEC-02/09** — enforce https + scheme allowlist on appcast/download URLs.
11. **DATA-04 / DATA-05** — give the indexing thread its own SQLite connection and add rollback on batch failure.

### Post-1.0 (maintainability & lower-severity)
12. **QUAL-03/04/05/08** — decompose the God constructors and the tab-dispatch chain; consolidate `metadata.py` globals.
13. Remaining Low/Info items (BUG-04…10, DATA-07…13, SEC-NET-03/04/05, SEC-EXEC-03/05/06/07, QUAL-06/07/09–15) as cleanup.
14. **SEC-EXEC-12** — confirm `requests==2.34.2` is a real release; set a refresh cadence for `yt-dlp` / `Pillow` / bundled VLC.
15. Before any future **in-place** auto-updater: require asymmetric signature verification (SEC-EXEC-01).

---

## 10. Appendix A — Verification performed by the lead reviewer

Independent ground-truth scans and direct source reads confirmed:

| Claim | How verified | Result |
|---|---|---|
| No `shell=True` / `os.system` / `os.popen` | grep across `lyon/` | ✓ None — all subprocess calls pass arg lists (`replaygain`, `ctdb_verify`, `ripper`, `disc_macos`) |
| No `verify=False` (TLS bypass) | grep across `lyon/` | ✓ None |
| All untrusted XML via `defusedxml` | grep for `etree`/`minidom`/`sax`/`defusedxml` | ✓ Confirmed (only `xml.sax.saxutils.escape` for output escaping) |
| DLNA defaults to `0.0.0.0` | read `settings.py:311,358` | ✓ Confirmed (SEC-NET-01) |
| Updater is notify-only, no signature | read `updater.py` docstring/body | ✓ "signatures omitted for the v1.0 unsigned ship" (SEC-EXEC-01) |
| `seek()`/`pause()` don't cancel prebuffer | read `player.py:289-308,345-347` | ✓ Confirmed vs `stop()`/`cleanup()` which do (BUG-01/02) |
| Smart-playlist `LIMIT` interpolation | read `smart_playlist.py:150` | ✓ `f"LIMIT {spec.limit}"` (DATA-01) |
| `_read_tags` TEMP-DIAG block | read `library.py:1643-1660` | ✓ Confirmed verbatim (QUAL-02/DATA-06) |
| Library SQL parameterization | grep `execute(` + f-string/SQL audit | ✓ Values parameterized; identifiers from constants/allowlists |

## Appendix B — Full findings index

| ID | Sev | Category | Title |
|---|---|---|---|
| SEC-NET-01 | Medium | Security | DLNA binds 0.0.0.0 with coarse IP allowlist ✓ |
| SEC-NET-02 | Medium | Security | SSRF in feed/discovery/artwork fetches |
| SEC-NET-03 | Low | Security | Cast SOAP to unvalidated renderer URLs |
| SEC-NET-04 | Low | Security | `_didl` double-escaping |
| SEC-NET-05 | Low/Info | Security | friendlyName reflected (escaped) |
| SEC-NET-06 | Info | Security | Scrobbler secret handling (OK; at-rest note) |
| SEC-NET-07 | Info | Security | Non-HTTP stream schemes accepted |
| SEC-EXEC-01 | Medium | Security | No update signature; unsigned Win installer ✓ |
| SEC-EXEC-02 | Low | Security | Download URL opened w/o scheme allowlist |
| SEC-EXEC-03 | Medium | Security | Last.fm secret baked into builds |
| SEC-EXEC-04 | Medium | Security | macOS VLC DMG checksum skippable |
| SEC-EXEC-05 | Low | Security | fpcalc (Win) downloaded w/o SHA-256 |
| SEC-EXEC-06 | Low | Security | Signing cert in predictable /tmp path |
| SEC-EXEC-07 | Low | Security | API tokens plaintext in settings.json |
| SEC-EXEC-09 | Low | Security | appcast URL settable, no https enforcement |
| SEC-EXEC-10 | Info | Security | DLL search-path mutation (OK) |
| SEC-EXEC-11 | Info | Security | Diagnostics include paths/URLs (by design) |
| SEC-EXEC-12 | Info | Security | Dependency pin review |
| DATA-01 | Medium | Security | Smart-playlist LIMIT interpolation ✓ |
| DATA-02 | Medium | Security | No size cap on CUE/M3U/PLS (DoS) |
| DATA-03 | Medium | Security | CUE FILE path traversal |
| DATA-10 | Low | Security | M3U/PLS UNC / file:// handling |
| BUG-01 | High | Bug | Gapless prebuffer not cancelled on seek ✓ |
| BUG-02 | High | Bug | Gapless prebuffer survives pause ✓ |
| BUG-03 | Medium | Bug | Double play-count on gapless end |
| BUG-04 | Medium | Bug | ICY metadata race after set_source |
| BUG-05 | Medium | Bug | Unavailable backend pause() emits "stopped" |
| BUG-06 | Medium | Bug | Re-entrant crossfade in position_changed |
| BUG-07 | Low | Bug | previous() at a track boundary |
| BUG-08 | Low | Bug | Lyrics worker reads Track off-thread (latent) |
| BUG-09 | Low | Bug | Deferred video-handoff lambdas brittle |
| BUG-10 | Low | Bug | set_replaygain mid-crossfade volume jump |
| DATA-04 | Medium | Bug | Shared-connection batch commit leakage |
| DATA-05 | Medium | Bug | No rollback → half-committed batches |
| DATA-07 | Low | Bug | add_to_playlist position/duplicate handling |
| DATA-08 | Low | Bug | CUE unchanged fast-path keyed on .cue stat |
| DATA-09 | Low | Bug | CUE interior-track duration fallback |
| DATA-11 | Low | Bug | Path normalization inconsistency |
| DATA-12 | Low | Bug | Unbounded CUE TRACK integer |
| DATA-13 | Info | Bug | MD5 sampled hash dup false-positives |
| QUAL-02/DATA-06 | High | Quality | TEMP-DIAG block live in _read_tags ✓ |
| QUAL-01 | High | Quality | Silent except: pass (~15 sites) |
| QUAL-03 | Medium | Quality | LibraryView.__init__ 328 lines |
| QUAL-04 | Medium | Quality | MainWindow.__init__ 277 lines |
| QUAL-05 | Medium | Quality | _ensure_tab_view if-chain |
| QUAL-06 | Medium | Quality | NowPlayingView._settings direct assignment |
| QUAL-07 | Medium | Quality | Optional[X] vs X \| None |
| QUAL-08 | Medium | Quality | metadata.py module globals |
| QUAL-09 | Low | Quality | Magic timer intervals |
| QUAL-10 | Low | Quality | Ripper.run 180 lines |
| QUAL-11 | Low | Quality | Ripper logs only via Qt signal |
| QUAL-12 | Low | Quality | Loose `Signal(object)` + isinstance |
| QUAL-13 | Low | Quality | Test coverage gaps |
| QUAL-14 | Info | Quality | knowledge_base_dialog inline HTML |
| QUAL-15 | Info | Quality | closeEvent duplication |

*✓ = independently verified against source by the lead reviewer.*

---

*Report generated 2026-05-29 from a 5-agent parallel review of Sea Lyon Media Manager `0.9.0-rc2` (branch `LMM-DEV`). No source files were modified. This is an AI-assisted review; treat it as expert input to be confirmed by the maintainer, not a guarantee of completeness.*
