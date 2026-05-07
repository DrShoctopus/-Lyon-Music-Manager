"""Spotify-inspired dark theme.

Palette:
- App background:  #121212
- Card / panel:    #181818  (hover #282828)
- Sidebar:         #000000
- Player bar:      #181818
- Text primary:    #FFFFFF
- Text secondary:  #B3B3B3
- Accent green:    #1DB954  (hover #1ED760)
- Subtle border:   #2A2A2A
"""

SPOTIFY_QSS = r"""
* { color: #ffffff; font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 9pt; }

QMainWindow, QWidget#root {
    background: #000000;
}

/* App content frame */
QFrame#content, QWidget#contentArea {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1f1f1f, stop:0.5 #141414, stop:1 #121212);
}

/* Sidebar */
QFrame#sidebar {
    background: #000000;
    border-right: 0;
    min-width: 232px; max-width: 280px;
}
QLabel#sidebarTitle {
    color: #ffffff; font-weight: 700; font-size: 18pt;
    padding: 18px 20px 8px 20px;
    letter-spacing: 0.5px;
}
QPushButton#navItem {
    background: transparent;
    color: #b3b3b3;
    border: none;
    text-align: left;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 11pt;
    min-height: 36px;
}
QPushButton#navItem:hover  { color: #ffffff; }
QPushButton#navItem:checked {
    color: #ffffff;
    background: #1f1f1f;
    border-left: 3px solid #1DB954;
    padding-left: 17px;
}
QFrame#sidebarDivider { background: #2a2a2a; max-height: 1px; min-height: 1px; }

/* Top header (search / breadcrumb) */
QFrame#topHeader {
    background: rgba(0, 0, 0, 90);
    border: 0;
    min-height: 56px;
    max-height: 56px;
}

/* Lists / tables */
QTreeView, QListView, QTableView {
    background: #121212;
    alternate-background-color: #161616;
    border: 0;
    selection-background-color: #2a2a2a;
    selection-color: #ffffff;
    gridline-color: #1f1f1f;
    outline: 0;
}
QTreeView::item, QListView::item, QTableView::item {
    padding: 6px 4px;
    border: 0;
}
QTreeView::item:hover, QListView::item:hover, QTableView::item:hover {
    background: #1f1f1f;
}
QHeaderView::section {
    background: #121212;
    color: #b3b3b3;
    padding: 6px 10px;
    border: 0;
    border-bottom: 1px solid #2a2a2a;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 8pt;
    letter-spacing: 0.5px;
}

/* Headings inside views */
QLabel#sectionTitle {
    color: #ffffff; font-weight: 700; font-size: 22pt;
    padding: 14px 20px 4px 20px;
}
QLabel#sectionSubtitle {
    color: #b3b3b3; padding: 0 20px 8px 20px;
}

/* Buttons */
QPushButton {
    background: #2a2a2a;
    color: #ffffff;
    border: 0;
    border-radius: 16px;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton:hover  { background: #3a3a3a; }
QPushButton:pressed { background: #1a1a1a; }
QPushButton:disabled { color: #6a6a6a; background: #1a1a1a; }

QPushButton#accent {
    background: #1DB954;
    color: #000000;
    font-weight: 700;
    padding: 10px 28px;
    border-radius: 22px;
}
QPushButton#accent:hover  { background: #1ED760; }
QPushButton#accent:pressed { background: #18a049; }

QPushButton#ghost {
    background: transparent;
    color: #b3b3b3;
    border: 1px solid #565656;
}
QPushButton#ghost:hover { color: #ffffff; border-color: #ffffff; }

/* Inputs */
QLineEdit, QComboBox, QSpinBox {
    background: #2a2a2a;
    border: 0;
    border-radius: 18px;
    padding: 8px 14px;
    color: #ffffff;
    selection-background-color: #1DB954;
    selection-color: #000000;
    min-height: 18px;
}
QLineEdit:focus, QComboBox:focus { background: #3a3a3a; }
QLineEdit#searchBox {
    background: #ffffff;
    color: #000000;
    padding-left: 36px;
}

/* Sliders (transport + volume) */
QSlider::groove:horizontal {
    height: 4px;
    background: #4d4d4d;
    border: 0;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #b3b3b3;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 0;
    width: 12px; height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider:hover::sub-page:horizontal { background: #1DB954; }
QSlider:hover::handle:horizontal   { background: #ffffff; }

/* Transport bar */
QFrame#transport {
    background: #181818;
    border-top: 1px solid #2a2a2a;
    min-height: 90px; max-height: 110px;
}
QLabel#nowPlayingTitle  { color: #ffffff; font-weight: 600; font-size: 11pt; }
QLabel#nowPlayingArtist { color: #b3b3b3; font-size: 9pt; }
QLabel#timeLabel        { color: #a7a7a7; font-size: 9pt; }

/* Round transport buttons (Spotify uses simple icon buttons, no gradient) */
QToolButton#transportBtn {
    background: transparent;
    color: #b3b3b3;
    border: 0;
    border-radius: 16px;
    min-width: 32px; min-height: 32px;
    font-size: 14pt;
    padding: 0;
}
QToolButton#transportBtn:hover     { color: #ffffff; }
QToolButton#transportBtn:checked   { color: #1DB954; }
QToolButton#transportPlay {
    background: #ffffff;
    color: #000000;
    border-radius: 18px;
    min-width: 36px; min-height: 36px;
    font-size: 14pt;
    font-weight: bold;
}
QToolButton#transportPlay:hover { background: #f5f5f5; }

/* Album / playlist cards */
QFrame#card {
    background: #181818;
    border-radius: 8px;
    padding: 16px;
}
QFrame#card:hover { background: #282828; }
QLabel#cardTitle    { color: #ffffff; font-weight: 700; font-size: 10pt; }
QLabel#cardSubtitle { color: #b3b3b3; font-size: 9pt; }

/* Status bar */
QStatusBar {
    background: #000000;
    color: #b3b3b3;
    border-top: 1px solid #1f1f1f;
}
QStatusBar::item { border: 0; }

/* Progress */
QProgressBar {
    background: #2a2a2a;
    border: 0;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    height: 8px;
}
QProgressBar::chunk {
    background: #1DB954;
    border-radius: 4px;
}

/* Scrollbars */
QScrollBar:vertical {
    background: transparent; width: 12px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #4d4d4d; min-height: 30px; border-radius: 6px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #6a6a6a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent; height: 12px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #4d4d4d; min-width: 30px; border-radius: 6px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #6a6a6a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* Splitter / menus / message boxes */
QSplitter::handle { background: #2a2a2a; }
QMenu  { background: #282828; border: 1px solid #3a3a3a; padding: 4px; }
QMenu::item         { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: #3a3a3a; color: #ffffff; }
QMenuBar { background: #000000; color: #b3b3b3; }
QMenuBar::item:selected { background: #1f1f1f; color: #ffffff; }

QMessageBox, QDialog { background: #181818; }
QDialogButtonBox QPushButton { min-width: 80px; }

/* Backwards-compat alias used by the old WMP imports */
"""

# Keep the old name importable so nothing breaks during transition.
WMP_QSS = SPOTIFY_QSS
