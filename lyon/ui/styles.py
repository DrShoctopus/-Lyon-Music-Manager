"""Windows Media Player 11 / 12 inspired Qt stylesheet.

Aesthetic notes:
- Dark gradient header (teal/blue) with reflective gloss
- Black content area
- Orange accent (the WMP "burn/sync" highlight color)
- Rounded transport bar at the bottom
"""

WMP_QSS = r"""
* { color: #e8e8e8; font-family: "Segoe UI", "Tahoma", sans-serif; font-size: 9pt; }

QMainWindow, QWidget#root {
    background: #0b0b0e;
}

/* Title / chrome bar */
QFrame#titlebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0d3d63, stop:0.49 #0a2a44, stop:0.5 #061a2c, stop:1 #0a2740);
    border-bottom: 1px solid #000;
    min-height: 40px;
}
QLabel#titleLabel {
    color: #d8eaff;
    font-weight: 600;
    padding-left: 14px;
    letter-spacing: 1px;
}

/* Top section tabs (Now Playing / Library / Rip / Burn / Sync style) */
QFrame#tabbar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #103754, stop:1 #06182a);
    border-bottom: 1px solid #000;
    min-height: 36px;
}
QPushButton#navTab {
    background: transparent;
    color: #cfe2f5;
    border: none;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton#navTab:hover {
    color: #ffffff;
    background: rgba(255,255,255,0.05);
}
QPushButton#navTab:checked {
    color: #ffb24d;
    border-bottom: 2px solid #ffb24d;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,178,77,0.15), stop:1 transparent);
}

/* Sidebar & lists */
QTreeView, QListView, QTableView {
    background: #0e1116;
    alternate-background-color: #14181f;
    border: 1px solid #1c222b;
    selection-background-color: #1f5fa5;
    selection-color: #ffffff;
    gridline-color: #1c222b;
}
QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2a3340, stop:1 #161c25);
    color: #d8e2ee;
    padding: 4px 8px;
    border: 0;
    border-right: 1px solid #0a0d11;
    border-bottom: 1px solid #0a0d11;
}

/* Buttons */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2c3340, stop:1 #161c25);
    color: #e8edf5;
    border: 1px solid #0a0d11;
    border-radius: 3px;
    padding: 5px 12px;
    min-width: 60px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3a4658, stop:1 #1c2330);
    border: 1px solid #ffb24d;
}
QPushButton:pressed { background: #0e131a; }
QPushButton:disabled { color: #555; background: #1a1f27; }

QPushButton#accent {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffb24d, stop:1 #d97a1a);
    color: #1a1006;
    font-weight: 700;
    border: 1px solid #5a3308;
}
QPushButton#accent:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffc36a, stop:1 #e98a25);
}

/* Inputs */
QLineEdit, QComboBox, QSpinBox {
    background: #0c0f14;
    border: 1px solid #2a3340;
    border-radius: 2px;
    padding: 4px 6px;
    selection-background-color: #1f5fa5;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #ffb24d; }

/* Sliders (transport bar + volume) */
QSlider::groove:horizontal {
    height: 8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #07090c, stop:0.48 #1b2028, stop:0.52 #444a55, stop:1 #131820);
    border: 1px solid #0a0c10;
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a8f6ff, stop:0.52 #2f83ff, stop:1 #162d93);
    border: 1px solid #38c7ff;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: qradialgradient(cx:0.35, cy:0.25, radius:0.8,
        stop:0 #d8f6ff, stop:0.42 #75b9ff, stop:0.74 #1c5ed0, stop:1 #081f5b);
    border: 1px solid #05070b;
    width: 22px;
    margin: -8px 0;
    border-radius: 11px;
}
QSlider::handle:horizontal:hover {
    border: 1px solid #5bf6ff;
}

/* Transport bar */
QFrame#transport {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #66686d, stop:0.09 #51545a, stop:0.48 #3c3f44,
        stop:0.50 #23262b, stop:1 #15181c);
    border: 1px solid #101216;
    border-top: 1px solid #8d9094;
    border-radius: 43px;
    min-height: 86px;
}
QLabel#transportThumb {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3f444c, stop:1 #12161d);
    border: 1px solid #05070a;
    border-radius: 12px;
    padding: 3px;
}
QWidget#transportMeta {
    background: transparent;
}
QLabel#nowPlayingTitle  { color: #f6fbff; font-weight: 700; font-size: 12pt; }
QLabel#nowPlayingArtist { color: #9feaf2; font-size: 10pt; }
QLabel#timeLabel        { color: #d1d8e2; font-size: 9pt; }
QLabel#volumeIcon       { color: #f1f8ff; font-size: 24pt; font-weight: 700; }

QFrame#transportUtilityCluster, QFrame#transportNavCluster, QFrame#transportVolumeCluster {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #70737a, stop:0.12 #4e535b, stop:0.48 #32363d,
        stop:0.50 #181b20, stop:1 #0b0d11);
    border: 1px solid #15171b;
    border-radius: 13px;
}
QFrame#transportNavCluster {
    border-radius: 16px;
}
QFrame#transportVolumeCluster {
    border-radius: 24px;
    min-width: 188px;
    min-height: 48px;
}

/* Glossy segmented transport buttons */
QToolButton#transportBtn, QToolButton#transportUtilityBtn {
    background: transparent;
    border: 0;
    border-right: 1px solid #111317;
    color: #f5f8fb;
    font-weight: 800;
    font-size: 22pt;
    min-width: 62px;
    min-height: 54px;
    padding-bottom: 2px;
}
QToolButton#transportUtilityBtn {
    font-size: 18pt;
    min-width: 48px;
}
QToolButton#transportBtn:hover, QToolButton#transportUtilityBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,0.16), stop:0.50 rgba(255,255,255,0.04),
        stop:1 rgba(49,227,255,0.22));
    color: #ffffff;
}
QToolButton#transportBtn:pressed, QToolButton#transportUtilityBtn:pressed,
QToolButton#transportUtilityBtn:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22262d, stop:0.50 #0b0d11, stop:1 #163e4a);
    color: #7ff7ff;
}
QToolButton#transportPlay {
    min-width: 88px;
    min-height: 88px;
    border-radius: 44px;
    background: qradialgradient(cx:0.38, cy:0.25, radius:0.86,
        stop:0 #ffffff, stop:0.18 #c9ecff, stop:0.42 #4f91ff,
        stop:0.70 #164cbf, stop:0.88 #102c66, stop:1 #071326);
    color: #ffffff;
    font-weight: 900;
    font-size: 34pt;
    border: 3px solid #262a31;
    padding-left: 6px;
}
QToolButton#transportPlay:hover {
    background: qradialgradient(cx:0.38, cy:0.25, radius:0.86,
        stop:0 #ffffff, stop:0.18 #d8fbff, stop:0.42 #70d7ff,
        stop:0.68 #2268e2, stop:0.86 #123b8a, stop:1 #071326);
    border: 3px solid #65f4ff;
}
QToolButton#transportPlay:pressed {
    background: qradialgradient(cx:0.5, cy:0.55, radius:0.78,
        stop:0 #1b77ff, stop:0.55 #113a91, stop:1 #061225);
    padding-top: 3px;
}

/* Status bar */
QStatusBar {
    background: #0a0d11;
    color: #aab3c0;
    border-top: 1px solid #000;
}

QProgressBar {
    background: #0c0f14;
    border: 1px solid #2a3340;
    border-radius: 2px;
    text-align: center;
    color: #f0f0f0;
    height: 14px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffd17a, stop:1 #c87018);
    border-radius: 2px;
}

QScrollBar:vertical {
    background: #0c0f14; width: 12px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a3340; min-height: 30px; border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: #3a4658; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QSplitter::handle { background: #161c25; }
QMenu { background: #14181f; border: 1px solid #2a3340; }
QMenu::item:selected { background: #1f5fa5; }
"""
