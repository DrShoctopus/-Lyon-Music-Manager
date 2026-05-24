# HiDPI / Display Configuration Matrix

Sea Lyon Media Manager runs on the Qt 6 / PySide6 widget stack. Qt
handles per-monitor DPI scaling reasonably well out of the box, but
custom-painted widgets (transport bar, Now Playing cover art, library
grid thumbnails) need explicit verification at common Windows scale
factors.

This document records:

1. The configurations we test before tagging a release.
2. Known visual issues at non-100% scale.
3. The Qt scaling policy the app uses, for reference.

## Qt scaling policy

`lyon/app.py` calls:

```python
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
```

`PassThrough` honours Windows' fractional scale (e.g. 125%, 150%, 175%)
without rounding to the nearest integer. This gives the cleanest result
on common laptop screens, at the cost of a small risk of one-pixel
misalignments in custom-painted regions.

Qt automatically picks `@2x` high-DPI variants of `.png` assets when
they exist; we currently ship `1x` only and rely on Qt's bilinear
downscale at fractional sizes.

## Verification matrix

For each release, spot-check the rows marked **required**. The
**recommended** rows are nice-to-have but not blockers.

| Resolution     | Scale | Notes                                   | Status |
|----------------|-------|-----------------------------------------|--------|
| 1920×1080      | 100%  | The reference configuration. Required.  | ☐      |
| 1920×1080      | 125%  | Common Windows 10 laptop default.       | ☐      |
| 2560×1440      | 100%  | Required.                               | ☐      |
| 2560×1440      | 125%  | Common 1440p laptop default.            | ☐      |
| 2560×1440      | 150%  | Recommended.                            | ☐      |
| 3840×2160      | 150%  | Required (4K @ Win10 default).          | ☐      |
| 3840×2160      | 175%  | Recommended.                            | ☐      |
| 3840×2160      | 200%  | Required (4K @ Win11 default).          | ☐      |
| 3440×1440      | 100%  | Ultrawide; recommended.                 | ☐      |
| 1366×768       | 100%  | Old netbook floor; recommended.         | ☐      |
| 1366×768       | 125%  | Same; recommended.                      | ☐      |

To change scale on Windows 10/11:
**Settings → System → Display → Scale and layout**.

To change resolution for testing without resizing the physical monitor,
use **Display → Display resolution** or a virtual machine with the
target resolution.

## Per-screen checks

At every configuration above, verify each row:

| # | Surface | What to check |
|---|---------|---------------|
| 1 | Window chrome | Title bar buttons aligned; window can be resized. |
| 2 | Top tab bar | All 8 tab labels visible without clipping. |
| 3 | Library tab | Column headers aligned with cells; rating stars correct width. |
| 4 | Now Playing | Cover art square (not stretched); blurred background fills evenly. |
| 5 | Transport bar | Play/pause/seek icons crisp; time labels not clipped. |
| 6 | EQ dialog | 10 sliders evenly spaced; band labels readable. |
| 7 | Settings dialog | Tab bar fits the window without scrolling. |
| 8 | First-run wizard | Logo + buttons centered; long folder paths don't break layout. |
| 9 | Toast notifications | Toast positions correctly (bottom-right of main window). |
| 10 | About dialog | Tabs scale; license scroll area resizes with the dialog. |
| 11 | Update dialog | Release-notes HTML readable; buttons not clipped. |
| 12 | YouTube acknowledgement | Checkbox + body text fit; OK button only enables after check. |
| 13 | Video player | Video aspect ratio preserved; fullscreen icons crisp. |
| 14 | Diagnostics dialog | Long status messages wrap, not clip. |

## Known issues (v0.8.0 → v1.0)

| Surface | Configuration | Issue | Severity | Tracking |
|---|---|---|---|---|
| _none currently logged_ |  |  |  |  |

Update this section as issues surface during Track F (Week 4) smoke
runs. Each entry should link to a GitHub issue with a screenshot.

## Multi-monitor

The app does not deliberately migrate windows between monitors on a
DPI change. If a user drags the main window from a 100% monitor to a
200% monitor:

- Qt reflows the layout automatically.
- Custom-painted widgets re-paint with the new DPR.
- The user should not need to restart the app.

Verify this when convenient; not a release blocker if rough edges
appear on multi-monitor moves.

## Suppressing fractional scaling for one user

If a user hits a serious layout bug at a fractional scale, they can
work around it by setting `QT_SCALE_FACTOR_ROUNDING_POLICY=Round`
before launch:

```cmd
set QT_SCALE_FACTOR_ROUNDING_POLICY=Round
"%LOCALAPPDATA%\Programs\Sea Lyon Media Manager\LyonMusicManager.exe"
```

This is a debug-only workaround and changes the app's appearance
on every machine that uses fractional scaling.

## See also

- [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) §M — abbreviated
  matrix wired into the release-blocker sheet.
- Qt high-DPI documentation:
  <https://doc.qt.io/qt-6/highdpi.html>
