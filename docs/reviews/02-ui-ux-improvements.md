# Report 2: UI/UX Improvements

Review date: 2026-05-15

Scope: static UI review of PySide widget construction, information architecture, desktop ergonomics, accessibility, and workflow fit. Visual runtime review was blocked because this machine's active Python environment does not have `PySide6`.

## Summary

Sea Lyon has a coherent Windows Media Player-inspired direction, clear primary tabs, and useful domain workflows. The main UX risk is that the interface is already dense and text-heavy at version 0.5.0. The app would benefit from clearer task hierarchy, modern library affordances, and stronger feedback during long operations.

## Recommended Improvements

### 1. Make the top navigation less crowded

Evidence: `lyon/ui/main_window.py:90-120` creates five primary tabs plus Queue, 10 Band EQ, and Settings as same-style text buttons in one horizontal strip.

Problem: primary destinations and secondary tools compete visually. At smaller widths this row will be hard to scan and likely compress badly.

Suggested fix:

- Keep only primary destinations in the tab strip: Now Playing, Library, Rip, YouTube, Video.
- Move Queue, EQ, Settings, Diagnostics, and About into a compact toolbar/menu area with icons and tooltips.
- Add keyboard shortcuts to command actions but keep shortcut hints in tooltips or menus, not persistent body text.

### 2. Modernize transport controls and accessibility

Evidence: `lyon/ui/now_playing.py:171-182` and `lyon/ui/now_playing.py:246-250` use symbolic text and emoji for shuffle, repeat, stop, previous, next, and mute. Only the custom play/pause button has an accessible name.

Problem: symbols such as `>>`, `M`, and emoji mute state can render inconsistently across platforms and are weak for screen readers.

Suggested fix:

- Use Qt theme icons or checked-in SVG icons for transport actions.
- Set `accessibleName` and `accessibleDescription` on every transport button.
- Give shuffle and repeat visible state feedback beyond color alone, for example a checked icon variant plus tooltip text.

### 3. Rework the bottom transport for narrow windows

Evidence: the transport bar has fixed/minimum widths across metadata, center controls, and volume at `lyon/ui/now_playing.py:165-266`; the main window minimum is `900x600` at `lyon/ui/main_window.py:71`.

Problem: the transport is the densest part of the app and is likely to crowd the library and video workflows.

Suggested fix:

- Collapse album art and volume into a second row below 1000 px.
- Hide secondary controls behind an overflow button below 900 px.
- Keep seek, play/pause, previous, and next always visible.

### 4. Add richer library browsing modes

Evidence: `lyon/ui/library_view.py:30-97` provides a three-pane Artists, Albums, Tracks browser plus search. The schema supports genre/year/artwork, but the UI does not expose them as first-class filters.

Problem: large libraries need album-art browsing, sortable columns, filters, and saved views.

Suggested fix:

- Add a view toggle: Albums, Artists, Tracks, Videos.
- Add column sorting and visible filters for genre, year, file type, bitrate, sample rate, and missing artwork.
- Add an album grid/list hybrid using existing `artwork_path`.

### 5. Turn empty and blocked states into actions

Evidence: the Library empty state is plain instructional text at `lyon/ui/library_view.py:99-104`. The unavailable video pane describes missing libVLC at `lyon/ui/video_player_view.py:285-301`.

Problem: empty states tell the user what happened, but do not directly advance the next action.

Suggested fix:

- Put "Add Folder", "Open Settings", and "Run Diagnostics" buttons into the library empty state.
- Put "Run Diagnostics" and "Open Build Guide" into the libVLC unavailable state.
- For YouTube unavailable states, route to Diagnostics rather than only showing install text.

### 6. Improve long-running workflow feedback

Evidence: ripping has a per-track percent column, a global progress bar, and a status label, but no structured status states or retry controls in `lyon/ui/ripper_view.py:241-255` and `lyon/ui/ripper_view.py:584-598`.

Problem: when ripping or metadata lookup partially fails, users need to know which action failed, which tracks are safe, and what to do next.

Suggested fix:

- Use status values: Waiting, Reading, Encoding, Tagging, Verifying, Done, Failed, Cancelled.
- Add a "View failure details" button when a failure log is written.
- Add "Retry failed tracks" after partial rip failure.

### 7. Simplify the video control surface

Evidence: `lyon/ui/video_player_view.py:311-452` places Open File, Screenshot, Fullscreen, Library toggle, seek, play/stop, speed, audio track, subtitle track, subtitle file, volume, and mute on one dense surface.

Problem: this is powerful but visually heavy. It also mixes primary playback controls with setup controls.

Suggested fix:

- Keep seek and transport primary.
- Move audio track, subtitles, speed, screenshots, and sidebar visibility into a compact tools menu or segmented toolbar.
- Add recent files and resume position so users do not have to browse manually every time.

### 8. Add operation-level validation in Settings

Evidence: `SettingsDialog._accept()` accepts paths, metadata contact, API key, drive text, and format choices at `lyon/ui/settings_dialog.py:260-289` with minimal validation.

Problem: users can save invalid folders or a placeholder MusicBrainz contact and only discover issues later.

Suggested fix:

- Validate save paths and show inline warnings.
- Warn if MusicBrainz contact is still `example.invalid`.
- Add "Test metadata lookup", "Test ffmpeg", and "Test VLC" buttons on relevant tabs.

### 9. Add visual hierarchy to Now Playing

Evidence: `NowPlayingView` shows cover, title, artist, and album at `lyon/ui/now_playing.py:17-60`, but does not expose queue context, lyrics, quality, or file details.

Problem: the screen feels underused compared with the rest of the app.

Suggested fix:

- Add a compact queue preview and upcoming track.
- Add optional technical details: codec, bitrate, sample rate, ReplayGain/loudness once implemented.
- Add lyrics/artwork/artist-bio panel later if the metadata layer grows.

### 10. Add UI tests once PySide is available in CI

Suggested fix:

- Add smoke tests that instantiate `MainWindow` offscreen, switch each tab, open/close Queue and EQ, start/cancel dummy workers, and close the app cleanly.
- Add screenshot regression tests for minimum width, normal desktop, and high-DPI scale.
