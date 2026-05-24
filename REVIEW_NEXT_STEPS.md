# Code Review — Remaining Findings

Findings from the 2026-05-24 end-to-end review that were not addressed in the
current fix batch. Organized by priority.

---

## Medium Severity

### Thread-unsafe settings cache
**File:** `lyon/core/settings.py:456-461`

`get_cached_settings()` uses check-then-act without a lock. Background threads
(scrobbler, metadata) call this concurrently. A concurrent
`invalidate_settings_cache()` can hand a thread a stale Settings object.

**Fix:** Add a threading.Lock around the check-then-set, or use a module-level
lock consistent with the rest of the settings module.

---

### TOCTOU race in `move_path`
**File:** `lyon/core/library.py:693-731`

`move_path()` checks row existence under one lock, releases, then re-acquires
for the UPDATE. Another thread could delete the row in between, causing the
UPDATE to affect 0 rows and losing user metadata (ratings, play counts).

**Fix:** Perform the existence check and UPDATE in a single locked block.

---

### Iterator snapshot inconsistency in `all_tracks`
**File:** `lyon/core/library.py:906-927`

Keyset pagination yields outside the lock, so a concurrent library scan can
produce inconsistent results across page boundaries.

**Fix:** Either hold the lock across the full iteration (may hurt concurrency)
or accept the weak consistency and document it.

---

### Podcast feed fetch has no response size limit
**File:** `lyon/core/podcast.py:89-98`

`urlopen().read()` with no cap — a malicious feed URL can exhaust memory.

**Fix:** Use `response.read(MAX_FEED_SIZE)` with a reasonable limit (e.g. 10 MB).

---

## Low Severity

### Backward seek resets entire scrobble accumulator
**File:** `lyon/core/scrobbler.py:175-176`

Any backward seek (even 1ms) resets `_listened_ms` to 0. A user at 3:59 of a
4-minute track who accidentally seeks back loses their scrobble.

**Fix:** Only reset if the seek is larger than a threshold (e.g. 5 seconds), or
cap the penalty rather than zeroing entirely.

---

### `_activate_tab` stores out-of-range index
**File:** `lyon/ui/main_window.py:469-482`

`_last_confirmed_tab_idx = idx` executes outside the bounds guard. The
YouTube-gate revert logic could revert to an invalid tab index.

**Fix:** Move the assignment inside the `if 0 <= idx < len(self._TAB_ORDER)`
block.

---

### Updater thread `quit()` is ineffective
**File:** `lyon/ui/main_window.py:1795`

The update worker thread has no event loop, so `quit()` is a no-op. The 3s
`wait()` is shorter than the 10s HTTP timeout — window close can block.

**Fix:** Set a cancellation flag checked by the worker, or use a shorter HTTP
timeout that fits within the wait budget.

---

### Stale SOAP jobs processed after cast session change
**File:** `lyon/core/cast_controller.py:52-73`

The worker queue is never cleared between sessions. Stale jobs execute
wastefully (session_id filtering prevents state corruption but wastes network).

**Fix:** Drain the queue in `stop_cast()` before sending the sentinel, or add a
`clear()` helper.

---

### DLNA server binds to 0.0.0.0 without user configuration
**File:** `lyon/core/dlna_server.py:107`

The HTTP server is reachable from any network. The `_is_allowed_client` check
restricts responses to private IPs, but the socket is open on all interfaces.

**Fix:** Consider making the bind address configurable, or document the tradeoff.

---

## Code Quality

| Issue | Location | Notes |
|-------|----------|-------|
| Duplicated `find_ffmpeg` | ripper.py / yt_downloader.py | Already diverging |
| 4x user-agent construction | scrobbler, updater, podcast, metadata | Extract shared helper |
| Private `_podcast_user_agent` imported cross-module | main_window.py:29 | Make public or expose via interface |
| Dead wrapper `lookup_disc_with_fallback` | metadata.py:308 | Just calls `lookup_disc()` |
| Dead wrapper `_format_ext` | ripper.py:91 | Just calls `format_extension()` |
| Dead alias `_has_usable_metadata` | metadata.py:1288 | Identical to `_has_basic_metadata` |
| CI Python 3.11 vs local dev 3.14 | windows-build.yml:37 | Could mask version-specific bugs |
| Dynamic attr `_corrupt_backup_path` on dataclass | settings.py:434 | Invisible to type checkers |
| Unused import `is_placeholder_contact` | main_window.py:35 | Dead code |
| `Optional[]` vs `X | None` style inconsistency | multiple modules | Pick one convention |
