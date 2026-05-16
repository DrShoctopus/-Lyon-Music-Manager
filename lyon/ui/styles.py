"""Glossy blue media-player inspired Qt stylesheet.

Aesthetic notes:
- Graphite panels with soft, reflective highlights
- Electric cyan and cobalt gradients for active states
- A contained glassy transport button inside a rounded bottom control bar
- Matching cool-blue accents across tabs, inputs, progress, and selection
"""

WMP_QSS = r"""
* { color: #eef7ff; font-family: "Segoe UI", "Tahoma", sans-serif; font-size: 9pt; }

QMainWindow, QWidget#root {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #15181d, stop:0.45 #080b10, stop:1 #040609);
}

/* Header bar containing tab strip + tool buttons */
QWidget#headerBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2d3742, stop:0.5 #141a21, stop:1 #070a0f);
    border-bottom: 1px solid #000;
    min-height: 36px;
}

/* Tab bar */
QTabBar {
    background: transparent;
    border: none;
    alignment: left;
}
QTabBar::tab {
    background: transparent;
    color: #cdd9e6;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 18px;
    font-weight: 600;
    min-height: 32px;
}
QTabBar::tab:hover {
    color: #ffffff;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(107,231,255,0.18), stop:1 rgba(38,96,180,0.08));
}
QTabBar::tab:selected {
    color: #72f4ff;
    border-bottom: 2px solid #43e7ff;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(92,213,255,0.18), stop:1 rgba(49,112,224,0.08));
}
QTabBar::scroller {
    width: 20px;
}
QTabBar QToolButton {
    background: #1a2030;
    border: 1px solid #27313b;
    color: #cdd9e6;
}

/* Tool buttons in the header bar (Queue / EQ / Settings) */
QToolButton#navToolBtn {
    background: transparent;
    color: #8a9ab0;
    border: none;
    border-left: 1px solid #1c2430;
    padding: 8px 12px;
    min-width: 0;
    font-size: 8pt;
}
QToolButton#navToolBtn:hover {
    color: #c8d8e8;
    background: rgba(107,231,255,0.10);
    border-left: 1px solid #1c2430;
}
QToolButton#navToolBtn:pressed {
    color: #72f4ff;
    background: rgba(107,231,255,0.18);
    border-left: 1px solid #1c2430;
}

/* Sidebar & lists */
QTreeView, QListView, QTableView {
    background: #0a0e13;
    alternate-background-color: #111820;
    border: 1px solid #27313b;
    selection-background-color: #1466c7;
    selection-color: #ffffff;
    gridline-color: #1e2832;
}
QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3c4651, stop:0.49 #222a32, stop:0.5 #151a20, stop:1 #0b0e12);
    color: #dce8f4;
    padding: 4px 8px;
    border: 0;
    border-right: 1px solid #090c10;
    border-bottom: 1px solid #050607;
}

/* Keep hover tooltips readable when Windows high contrast themes alter the
   native tooltip palette. Fixed black/white colors avoid the app-wide
   foreground color blending into high-contrast tooltip backgrounds. */
QToolTip {
    background-color: #000000;
    color: #ffffff;
    border: 1px solid #ffffff;
    padding: 4px 6px;
    opacity: 255;
}

/* Buttons */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3b4651, stop:0.5 #1b222a, stop:1 #0a0e13);
    color: #edf8ff;
    border: 1px solid #06080b;
    border-radius: 6px;
    padding: 5px 12px;
    min-width: 60px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #52616d, stop:0.5 #26323c, stop:1 #101820);
    border: 1px solid #58eaff;
}
QPushButton:pressed { background: #070b10; }
QPushButton:disabled { color: #65707c; background: #171d24; }

QPushButton#accent {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #d7f8ff, stop:0.43 #69dfff, stop:0.44 #2073da, stop:1 #123976);
    color: #031221;
    font-weight: 700;
    border: 1px solid #7df4ff;
}
QPushButton#accent:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff, stop:0.43 #8df5ff, stop:0.44 #2b8fff, stop:1 #1853a2);
}

/* Inputs */
QLineEdit, QComboBox, QSpinBox {
    background: #070a0f;
    border: 1px solid #27313b;
    border-radius: 5px;
    padding: 4px 6px;
    selection-background-color: #1976d2;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #4eefff; }

/* Sliders (transport bar + volume) */
QSlider::groove:horizontal {
    height: 8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #07090c, stop:0.45 #171d24, stop:1 #343d47);
    border: 1px solid #030405;
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #102c83, stop:0.5 #1b8dff, stop:1 #68f3ff);
    border: 1px solid rgba(126,245,255,0.45);
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: qradialgradient(cx:0.45, cy:0.28, radius:0.78,
        stop:0 #ffffff, stop:0.24 #9ff4ff, stop:0.58 #267fe9, stop:1 #07142d);
    border: 1px solid #02050a;
    width: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider::handle:horizontal:hover {
    border: 1px solid #79fbff;
}

/* Transport bar — flattened, full-width, modern card */
QFrame#transport {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a2030, stop:1 #07090c);
    border-top: 1px solid #050607;
    min-height: 88px;
}
QLabel#transportThumb {
    background: #07090c;
    border: 1px solid #1c222b;
    border-radius: 6px;
    padding: 2px;
}
QLabel#nowPlayingTitle       { color: #72f4ff; font-weight: 700; font-size: 12.5pt; }
QLabel#nowPlayingArtist      { color: #d4e2ee; font-size: 10pt; }
QLabel#nowPlayingHeroTitle   { color: #72f4ff; }
QLabel#nowPlayingHeroArtist  { color: #d4e2ee; }
QLabel#timeLabel             { color: #aeb9c4; font-size: 9.5pt; }
QLabel#volumeIcon            { color: #e9f7ff; font-size: 18pt; padding-left: 2px; }

/* Transport buttons — flat dark base, cyan rim on hover/checked */
QToolButton#transportBtn {
    background: #1b222a;
    border: 1px solid #050607;
    border-radius: 6px;
    min-width: 42px;
    min-height: 40px;
    color: #f8fdff;
}
QToolButton#transportBtn:hover {
    background: #25323f;
    border: 1px solid #58eaff;
}
QToolButton#transportBtn:pressed {
    background: #0d141b;
    border: 1px solid #7ff8ff;
}
QToolButton#transportBtn:checked {
    background: #102845;
    border: 1px solid #7ff8ff;
}
QToolButton#transportBtn:disabled {
    background: #141a20;
    border: 1px solid #0a0d11;
}

/* Primary play/pause — cyan accent disc */
QToolButton#transportPlay {
    min-width: 62px;
    min-height: 62px;
    border-radius: 31px;
    background: qradialgradient(cx:0.4, cy:0.3, radius:0.85,
        stop:0 #8df7ff, stop:0.55 #2080e0, stop:1 #0a1a3a);
    color: #ffffff;
    border: 2px solid #1b2026;
}
QToolButton#transportPlay:hover {
    background: qradialgradient(cx:0.4, cy:0.3, radius:0.85,
        stop:0 #ffffff, stop:0.55 #3aa0ff, stop:1 #11286a);
    border: 2px solid #65efff;
}
QToolButton#transportPlay:pressed {
    background: qradialgradient(cx:0.5, cy:0.6, radius:0.82,
        stop:0 #2a8fff, stop:1 #040912);
}

/* Up Next queue preview in the Now Playing view */
QListWidget#queuePreview {
    background: #0a0e13;
    border: 1px solid #1c222b;
    border-radius: 6px;
}
QListWidget#queuePreview::item {
    padding: 6px 8px;
    border-bottom: 1px solid #131a21;
    color: #cfd6e2;
}
QListWidget#queuePreview::item:selected {
    background: #1466c7;
    color: #ffffff;
}

/* Status bar */
QStatusBar {
    background: #06080b;
    color: #aeb9c4;
    border-top: 1px solid #000;
}

QProgressBar {
    background: #070a0f;
    border: 1px solid #27313b;
    border-radius: 5px;
    text-align: center;
    color: #f0fbff;
    height: 14px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f3c9c, stop:0.55 #1b8dff, stop:1 #68f3ff);
    border-radius: 4px;
}

QScrollBar:vertical {
    background: #070a0f; width: 12px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #2e3945; min-height: 30px; border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: #466170; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QSplitter::handle { background: #161c23; }
QMenu { background: #111820; border: 1px solid #27313b; }
QMenu::item { padding: 6px 28px 6px 16px; }
QMenu::item:selected { background: #1466c7; }
QMenu::separator { height: 1px; background: #27313b; margin: 3px 8px; }

/* Video player */
QWidget#videoPlayerView {
    background: #0a0e13;
}
QWidget#videoSurface {
    background: #000000;
}
QFrame#videoControls {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a2030, stop:1 #07090d);
    border-top: 1px solid #000000;
    min-height: 104px;
}

QFrame#equalizerPanel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #101923, stop:1 #05080c);
    border: 1px solid #27313b;
    border-radius: 10px;
}
QLabel#sectionTitle {
    color: #72f4ff;
    font-weight: 700;
    font-size: 14pt;
}
QLabel#sectionHeading {
    color: #72f4ff;
    font-weight: 600;
    padding: 4px 6px;
}
QLabel#mutedText { color: #aeb9c4; }
QLabel#mutedTextSmall { color: #8a93a0; font-size: 8pt; }
QLabel#footerText {
    color: #8a93a0;
    font-size: 11px;
    padding: 2px 4px;
}
QLabel#emptyStateText {
    color: #8a93a0;
    font-size: 13px;
}
QLabel#hintText {
    color: #3a4a5a;
    font-size: 11pt;
}
QLabel#linkLabel { color: #43e7ff; }
QLabel#resultTitle {
    color: #72f4ff;
    font-weight: 600;
    font-size: 10pt;
}
QLabel#warningLabel { color: #e8a830; font-size: 8pt; }
"""
