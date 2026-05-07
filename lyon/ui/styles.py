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
    height: 12px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #050709, stop:1 #1a2230);
    border: 1px solid #000;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffd17a, stop:1 #c87018);
    border-radius: 6px;
}
QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f5f5f5, stop:1 #888);
    border: 1px solid #000;
    width: 20px;
    margin: -8px 0;
    border-radius: 10px;
}

/* Transport bar */
QFrame#transport {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a232f, stop:0.5 #0c1219, stop:1 #050709);
    border-top: 1px solid #000;
    min-height: 130px;
}
QLabel#nowPlayingTitle  { color: #ffb24d; font-weight: 600; font-size: 13pt; }
QLabel#nowPlayingArtist { color: #cfd6e2; font-size: 11pt; }
QLabel#timeLabel        { color: #aab3c0; font-size: 11pt; }

/* Round transport buttons */
QToolButton#transportBtn {
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.8,
        stop:0 #4a5666, stop:1 #0a0e14);
    border: 1px solid #000;
    border-radius: 30px;
    min-width: 60px; min-height: 60px;
    color: #e8edf5;
    font-size: 16pt;
}
QToolButton#transportBtn:hover {
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.8,
        stop:0 #6a7686, stop:1 #1a1e24);
}
QToolButton#transportPlay {
    min-width: 84px; min-height: 84px; border-radius: 42px;
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.8,
        stop:0 #ffd17a, stop:1 #803c08);
    color: #1a1006;
    font-weight: bold;
    font-size: 22pt;
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
