# Implementation Plan: UI/UX Modernization for Sea Lyon Media Manager

Target branch: `LMM-DEV` (read-only review until specific phases are approved).

50+ recommendations grouped into **7 implementation phases** ordered by dependency + ROI. Each phase is independently shippable so changes can land incrementally rather than as one giant PR.

---

## Phase 0 — Foundation (must land first)

These create reusable primitives the later phases depend on. Nothing user-visible yet, but unblocks everything.

| # | Change | Files | Effort |
|---|---|---|---|
| 0.1 | Create `lyon/ui/icons.py` — central icon loader that prefers SVG from `docs/brand/icons/`, falls back to `QStyle.standardIcon`, caches `QIcon` per name/size | new file, used by `now_playing.py`, `video_player_view.py`, `library_view.py` | S |
| 0.2 | Add SVG icon set to `docs/brand/icons/`: play, pause, stop, prev, next, shuffle, repeat-off, repeat-all, repeat-one, volume, volume-muted, queue, eq, settings, search, add, rip, youtube, video, library, grid, list, fullscreen, screenshot, chevron-left, chevron-right, more-horizontal, more-vertical | new assets | M (mostly asset work) |
| 0.3 | Consolidate inline `setStyleSheet` calls. Add named QSS classes in `styles.py`: `mutedText`, `mutedTextSmall`, `sectionTitle`, `sectionHeading`, `warningLabel`, `linkLabel`, `cardBg`, `cardBgHover`. Replace all inline `color:#...` strings across `library_view.py`, `now_playing.py`, `ripper_view.py`, `youtube_view.py`, `video_player_view.py`, `settings_dialog.py`, `first_run_dialog.py` | `styles.py` + sweep | M |
| 0.4 | Add `lyon/ui/theme.py` with a single source of truth for colors used in Python (e.g. status colors in `diagnostics_dialog.py:14-18`, video sidebar in `video_player_view.py:524-528`) | new file | S |
| 0.5 | Add `_scale_px(int) -> int` helper in `widgets.py` using `QApplication.devicePixelRatio()`; replace hard-coded sizes (68, 360, 42, 96, etc.) with helper calls | `widgets.py`, multiple views | M |

**Risk:** low. Pure refactor. Add a smoke test that imports each view to catch regressions.

---

## Phase 1 — Top-of-window restructure (recs 1.x, 2.1, 2.5, 11.2, 13.3)

User-visible win #1: cleaner chrome, fewer competing controls.

| # | Change | Files | Effort |
|---|---|---|---|
| 1.1 | Remove the custom `QFrame#titlebar` (`main_window.py:82-89`); rely on the native OS title bar. Add icon + version to `QMainWindow.setWindowIcon` via `branding.app_icon()` | `main_window.py:82-89`, `styles.py:19-30` | S |
| 1.2 | Split tab strip from tool buttons. Replace `QFrame#tabbar` with a real `QTabBar` for navigation + a right-aligned `QToolBar` of icon buttons for Queue / EQ / Settings (using `icons.py` from 0.1) | `main_window.py:91-124`, `styles.py:32-77` | M |
| 1.3 | Re-order tabs: Library, Now Playing, Video, Rip, YouTube. Update `_tab_buttons` map and default-selected tab. Keep file-menu wording aligned | `main_window.py:100-153` | S |
| 1.4 | Wire `Ctrl+1..Ctrl+5` shortcuts to the new `QTabBar` | `main_window.py:_build_menu` | S |
| 1.5 | macOS menu roles on QActions: `Settings → ApplicationSpecificRole`, `About → AboutRole`, `Quit → QuitRole` | `main_window.py:212-245` | S |
| 1.6 | Move "Custom Built For Chuck Lyon" out of the main About body into a "Dedicated to:" line | `main_window.py:423-431` | trivial |

**Risk:** medium — `QTabBar` styling will need new QSS rules. Keep the old `QFrame#tabbar` styles around until the swap is verified.

---

## Phase 2 — Transport controls overhaul (recs 2.2, 2.3, 2.6, 4.x, 7.2, 7.3)

The single highest-impact polish phase. Touches the most-used surface.

| # | Change | Files | Effort |
|---|---|---|---|
| 2.1 | Extend the custom-painted approach from `PlayPauseButton` (`now_playing.py:78-130`) to a `_TransportButton` base class that paints a fixed glyph from an SVG. Replace `_make_btn(...)` call sites for prev/next/stop/shuffle/repeat/mute with the new class | `now_playing.py:133-296`, new code | L |
| 2.2 | Repeat button: cycle a 3-state icon (off / all / one) instead of `⟳`/`⟳A`/`⟳1` text | `now_playing.py:298-304` | S |
| 2.3 | Volume/mute: replace `"Vol"`/`"Mut"` with speaker icons with 0/low/high/muted variants based on slider value | `now_playing.py:256-264, 325-337` | S |
| 2.4 | Flatten transport bar: drop `border-radius: 38px` capsule (`styles.py:181`) to 6-8px, remove `margin: 0 14px 10px 14px`, full-width to window edges | `styles.py:176-184` | S |
| 2.5 | Tone down multi-stop gradients across `styles.py` — keep cyan accent for active states, use 2-stop or flat backgrounds elsewhere. Reduce visual noise | `styles.py` (most rules) | M |
| 2.6 | Persist `volume` and `muted` separately for audio vs video, but share by default. Add a "Use shared volume" setting in Settings → Library; default true | `core/settings.py`, `core/player.py`, `video_player_view.py:419-424`, `settings_dialog.py` | M |
| 2.7 | Now Playing redesign: split into a 3-column layout — Cover (360px) | Metadata + format/codec strip + position | Compact queue list (scrollable, click to jump). Use existing `track_details` from `library_view.py:229-243` for the format strip | `now_playing.py:16-72` | L |

**Risk:** medium. Transport bar is the most-tested surface — write a smoke test that exercises play/pause/seek/volume after the refactor.

---

## Phase 3 — Library modernization (recs 1.3, 3.x)

| # | Change | Files | Effort |
|---|---|---|---|
| 3.1 | Add `QToolButton` view toggle (List ⇄ Grid) to library toolbar | `library_view.py:32-53` | S |
| 3.2 | Build `AlbumGridView` widget: `QListView` in `IconMode` with `setViewMode(QListView.IconMode)`, `setResizeMode(Adjust)`, `setSpacing`, custom `QStyledItemDelegate` that paints album art + title + artist below. Backed by an `albums()` library query | new file `lyon/ui/album_grid.py`, `library_view.py` | L |
| 3.3 | Wire grid view → click loads tracks in main pane, double-click plays album | `library_view.py`, `album_grid.py` | S |
| 3.4 | Enable `setSortingEnabled(True)` on the tracks table. Persist sort column + order in settings | `library_view.py:66-79`, `core/settings.py` | S |
| 3.5 | Add filter chip row above tracks table: Genre dropdown, Year range, File type, "Missing artwork only". Wire to `library.search(...)` with new filter args | `library_view.py`, `core/library.py` | L |
| 3.6 | Live-filter artists/albums panes as user types in search; add a visible "Clear search ✕" pill when search is active. Move into a "Search results" mode that bypasses the three panes | `library_view.py:330-342` | M |
| 3.7 | Move per-selection buttons (Play, Enqueue) above the tracks pane. Move library-level actions (Add Folder, Rescan) into a `+ Add Music` menu next to search | `library_view.py:32-53` | S |
| 3.8 | "+ Add Music" menu items: Add Folder…, Rip CD… (switches tab), Download from YouTube… (switches tab), Import Files… (file picker) | `library_view.py`, `main_window.py` | S |

**Risk:** medium. Grid view needs perf tuning for libraries with 5000+ albums (lazy thumbnail loading via `QPixmapCache`).

---

## Phase 4 — Workflow & feedback (recs 1.4, 5.x, 6.x, 13.4)

| # | Change | Files | Effort |
|---|---|---|---|
| 4.1 | Auto-detect inserted CDs: poll drive media-present every 2s (only when Rip tab not active). Show a non-modal toast: *"Audio CD detected in D:. [Open Rip tab] [Dismiss]"* | new file `lyon/ui/toast.py`, `main_window.py`, `core/cd_detect.py` | M |
| 4.2 | Rip toolbar reorganization: tuck Refresh Drives into a `⋮` overflow next to the drive combo; visual flow Detect → Search Online → Rip | `ripper_view.py:231-251` | S |
| 4.3 | Add a leading checkbox column to the tracks table; pass selected `track_numbers` to `RipRequest` | `ripper_view.py:289-302, 553-598`, `core/ripper.py` if needed | M |
| 4.4 | Promote "Search Online" near the status label; demote it from the Year row | `ripper_view.py:271-279` | trivial |
| 4.5 | Replace the status-label / progress-bar / retry-button stack with a single result banner widget. States: scanning, ripping (N/total), partial (with [Retry] [View log] [Open folder]), complete (with [Open folder]) | new component, `ripper_view.py:305-326, 668-686` | M |
| 4.6 | "Open folder" link in successful-rip banner uses existing `QDesktopServices.openUrl` pattern from `library_view.py:292-299` | `ripper_view.py` | trivial |
| 4.7 | YouTube: replace "Searching…" text with skeleton-row placeholders (gray rectangles matching `_THUMB_W`×`_THUMB_H`) | `youtube_view.py:166-170, 247-268` | S |
| 4.8 | YouTube: raise `_MAX_RESULTS` to 30 + add "Show more" footer that re-queries with offset (yt-dlp supports `ytsearch{N}`) | `youtube_view.py:23, 56-83` | M |
| 4.9 | YouTube result row: add hover-revealed "Watch" button that opens URL externally (`QDesktopServices.openUrl`) before user commits to download | `youtube_view.py:88-130` | S |
| 4.10 | YouTube unavailable state: add "Run Diagnostics" button (mirror library empty state pattern from `library_view.py:120-124`) | `youtube_view.py:194-201` | trivial |
| 4.11 | Status bar messages persist until next message instead of expiring after 3-5s. Add a separate transient toast widget for "scanning…" type ephemeral updates | `main_window.py:171-318` | S |
| 4.12 | Add a banner above the content stack when transport is hidden: *"Audio paused while ripping"* / *"Audio paused while video plays"* | `main_window.py:271-279` | S |

---

## Phase 5 — Video player (recs 7.x, 12.3)

| # | Change | Files | Effort |
|---|---|---|---|
| 5.1 | Auto-hide controls overlay: wrap `videoControls` frame in a `QGraphicsOpacityEffect`, install `eventFilter` on the surface for mousemove, fade out after 2.5s idle | `video_player_view.py:376-484` | M |
| 5.2 | Move "Open File" into a `+` menu button in the sidebar header, alongside the catalog count label | `video_player_view.py:334-336, 534-546` | S |
| 5.3 | Replace `▶` / `||` / `■` text glyphs with same icon set Phase 2 introduces | `video_player_view.py:406-429` | S |
| 5.4 | Top toolbar overflow at narrow widths: collapse Screenshot / Fullscreen / Sidebar buttons into a `⋮` menu when window < 1100px | `video_player_view.py:330-362` | M |
| 5.5 | Move Audio track / Subtitle track / Speed / Load Sub into a "Tools" popup menu; keep only seek + transport + volume + mute on the surface | `video_player_view.py:441-484` | M |
| 5.6 | Persist last-watched position per file (key by absolute path → hash) and offer "Resume from M:SS?" toast on reload | `core/settings.py` or new `core/playback_state.py`, `video_player_view.py:_load_path` | M |

---

## Phase 6 — Dialogs (recs 8.x, 9.x, 10.x)

| # | Change | Files | Effort |
|---|---|---|---|
| 6.1 | Settings dialog: resize default to 720×540; library folders list min-height 200 | `settings_dialog.py:37, 82` | trivial |
| 6.2 | Add helper text under "Music folder" and "Library folders" describing exactly what each does | `settings_dialog.py:59-98` | S |
| 6.3 | Add "Test" buttons next to MusicBrainz contact and TheAudioDB API key. Each fires a one-shot worker that runs a known-good query; show ✓/✗ result inline | `settings_dialog.py:178-191`, new helper in `core/metadata.py` | M |
| 6.4 | Replace the soft "example.invalid" warning with a save-time confirmation dialog when the placeholder is still in place | `settings_dialog.py:_accept, _check_contact` | S |
| 6.5 | Auto-populate `musicbrainz_contact` on first launch with `f"{getuser()}@{node()}"` | `core/settings.py` defaults | trivial |
| 6.6 | Add "Restore Defaults" button in dialog button row | `settings_dialog.py:50-55` | S |
| 6.7 | First-run dialog: demote "Skip Setup" to text-link style on the left, make "Save Setup" the accent button on the right | `first_run_dialog.py:70-75` | trivial |
| 6.8 | First-run dialog: replace plain dependency summary with colored badges (reuse `_STATUS_COLORS` from `diagnostics_dialog.py:14-18`) | `first_run_dialog.py:64-66` | S |
| 6.9 | Convert QueueDialog into a dockable side panel (`QDockWidget`) that slides from the right edge of `MainWindow`. Keep the existing dialog code path for the Ctrl+Q "detach" case | `queue_dialog.py`, `main_window.py:383-389` | L |
| 6.10 | Queue: enable `setDragDropMode(InternalMove)` on the table; wire `rowsMoved` signal to `player.move_queue_item` | `queue_dialog.py:28-42` | S |
| 6.11 | Queue: demote "Clear Queue" to a text-button or smaller secondary style. Add confirm dialog for destructive action | `queue_dialog.py:43-56` | trivial |

**Risk:** 6.9 is the biggest task. Keep the standalone dialog as fallback during transition.

---

## Phase 7 — Accessibility, responsive, branding (recs 2.7, 11.x, 12.x, 13.x)

| # | Change | Files | Effort |
|---|---|---|---|
| 7.1 | Sweep: set `accessibleName` + `accessibleDescription` on every QPushButton/QToolButton/QSlider/QComboBox/QLineEdit across all views | all UI files | M |
| 7.2 | Add `QSS` focus styles for `QPushButton:focus`, `QToolButton:focus`, `QSlider:focus`, `QListView::item:focus`, `QTableView::item:focus` | `styles.py` | S |
| 7.3 | Set explicit `setTabOrder()` in each view's `__init__` after layout | each view | M |
| 7.4 | Raise window minimum to 1050×680, or implement the collapsible transport (`now_playing.py:144-285` — hide volume row when width < 1000, hide thumb+meta when width < 850) | `main_window.py:71-72`, `now_playing.py` | M |
| 7.5 | Replace `"♪"` glyph cover fallback with `branding.app_icon()` scaled down | `widgets.py:9-32`, `now_playing.py:27,66,71`, `ripper_view.py:259,432` | S |
| 7.6 | Splash duration: tie to actual readiness — close splash when `MainWindow.show()` fires plus first frame painted, instead of fixed 1400ms | `branding.py:112-128`, `app.py` | S |

---

## Phase 8 — Testing (rec from report 02 item 10)

| # | Change | Files | Effort |
|---|---|---|---|
| 8.1 | Add `pytest-qt` to `requirements.txt` dev section | `requirements.txt` | trivial |
| 8.2 | Smoke test: instantiate `MainWindow` offscreen, switch each tab, open/close Queue + EQ + Settings dialogs, close cleanly | `tests/test_ui_smoke.py` (new) | M |
| 8.3 | Width-regression tests: render `MainWindow` at 900, 1100, 1400px and assert no widget is clipped (using `geometry()`) | `tests/test_ui_responsive.py` (new) | M |
| 8.4 | Snapshot tests for the rip status banner state machine (waiting / ripping / partial / complete) | `tests/test_ripper_view.py` (new) | M |

---

## Effort summary

| Phase | Description | Effort | User-visible? |
|---|---|---|---|
| 0 | Foundation (icons, theme, helpers) | M | No |
| 1 | Top-of-window restructure | M | Yes |
| 2 | Transport + Now Playing | L | Yes (huge) |
| 3 | Library modernization | L | Yes (huge) |
| 4 | Workflow & feedback | L | Yes |
| 5 | Video player | M | Yes |
| 6 | Dialogs | L | Yes |
| 7 | Accessibility / responsive / branding | M | Yes |
| 8 | Testing | M | No |

Legend: S = <2h, M = ~½ day, L = 1-2 days.

**Total ballpark:** ~3-4 weeks of focused single-developer effort, or 7-10 PRs landing incrementally.

---

## Recommended landing order

1. **Phase 0** (no behavior change) — merge first so later phases can lean on it.
2. **Phase 2** (transport overhaul) — biggest professional-feel jump.
3. **Phase 1** (top chrome) — quick win once Phase 0 ships.
4. **Phase 3** (library) — the most-asked-for "modern player" feature.
5. **Phase 4** (workflow polish) — flows feel cleaner.
6. **Phase 5** (video) — narrower scope, lower risk.
7. **Phase 6** (dialogs) — least urgent.
8. **Phase 7** (accessibility / responsive) — sweep across everything that landed.
9. **Phase 8** (tests) — once UI surface is stable.

---

## Open questions before starting

Two decisions needed before writing code:

1. **Icons:** source/commission an icon set, or use Qt's built-in `QStyle` standard icons + procedurally painted glyphs to avoid taking on an asset dependency?
2. **Branch strategy:** branch off `LMM-DEV` (and merge back to `LMM-DEV`) for each phase PR, or use a single feature branch like `LMM-DEV-ui-modernization` rebased per phase?
