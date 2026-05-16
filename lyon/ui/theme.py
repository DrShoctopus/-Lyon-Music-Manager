"""Central palette for Sea Lyon Media Manager.

Hex strings only — no Qt imports here so this module is safe to use from
both QSS-building code and runtime widgets, and is importable before
QApplication exists.
"""
from __future__ import annotations

# Text
TEXT_PRIMARY     = "#eef7ff"
TEXT_SECONDARY   = "#cfd6e2"
TEXT_MUTED       = "#aeb9c4"
TEXT_DIM         = "#8a93a0"
TEXT_HINT        = "#3a4a5a"
TEXT_INVERSE     = "#031221"

# Accent
ACCENT_CYAN        = "#72f4ff"
ACCENT_CYAN_BRIGHT = "#43e7ff"
ACCENT_BLUE        = "#1466c7"
ACCENT_FOCUS       = "#4eefff"

# Surface
BG_DEEP        = "#040609"
BG_PANEL       = "#0a0e13"
BG_PANEL_ALT   = "#111820"
BG_RAISED      = "#161c23"

# Borders
BORDER_DEFAULT = "#27313b"
BORDER_DARK    = "#050607"

# Status
STATUS_OK       = "#5ff59b"
STATUS_WARNING  = "#ffd166"
STATUS_ERROR    = "#ff6b6b"
STATUS_FAILED   = "#e85050"
WARNING_AMBER   = "#e8a830"
