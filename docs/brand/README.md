# Lyon Media Manager brand assets

This directory is the source of truth for the app's raster branding.

Expected files:

- `lyon-app-icon.png` — square app icon used by `lyon.ui.branding.app_icon()`.
- `lyon-splash.png` — startup splash screen used by `lyon.ui.branding.startup_splash_pixmap()`.

The app intentionally loads these image files directly rather than recreating the artwork with Qt drawing commands, so the runtime branding matches the supplied artwork exactly. If the files are missing, the app skips the splash and leaves the application icon unset instead of silently showing a recreated substitute.
