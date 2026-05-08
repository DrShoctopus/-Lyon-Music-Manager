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

/* Sliders (transport + volume).
   The transport bar uses Spotify green for the filled portion with a
   gentle vertical gradient -- shiny without being glossy. */
QSlider::groove:horizontal {
    height: 6px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2a2a2a, stop:1 #4a4a4a);
    border: 0;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #25e070, stop:0.5 #1DB954, stop:1 #128a3d);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: qradialgradient(cx:0.5, cy:0.4, radius:0.6,
        stop:0 #ffffff, stop:1 #cccccc);
    border: 0;
    width: 18px; height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QSlider:hover::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2af07a, stop:0.5 #1ED760, stop:1 #169a45);
}
QSlider:hover::handle:horizontal { background: #ffffff; }

/* Transport bar -- vertical gradient + thin Spotify-green top edge for
   a subtle metallic feel (shiny but not glossy). */
QFrame#transport {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1f1f1f, stop:0.45 #131313, stop:1 #050505);
    border-top: 2px solid #1DB954;
    min-height: 143px; max-height: 175px;
}
QLabel#nowPlayingTitle  { color: #ffffff; font-weight: 700; font-size: 17pt; }
QLabel#nowPlayingArtist { color: #b3b3b3; font-size: 13pt; }
QLabel#timeLabel        { color: #a7a7a7; font-size: 13pt; }

/* Round transport buttons -- soft radial gradient, larger icons. */
QToolButton#transportBtn {
    background: qradialgradient(cx:0.5, cy:0.45, radius:0.7,
        stop:0 #2e2e2e, stop:1 transparent);
    color: #cfcfcf;
    border: 0;
    border-radius: 26px;
    min-width: 51px; min-height: 51px;
    font-size: 22pt;
    padding: 0;
}
QToolButton#transportBtn:hover {
    color: #ffffff;
    background: qradialgradient(cx:0.5, cy:0.45, radius:0.75,
        stop:0 #3a3a3a, stop:1 transparent);
}
QToolButton#transportBtn:checked  { color: #1DB954; }
QToolButton#transportBtn:pressed  {
    background: qradialgradient(cx:0.5, cy:0.45, radius:0.75,
        stop:0 #1f1f1f, stop:1 transparent);
}

/* Play button -- Spotify-green orb with a soft top highlight. */
QToolButton#transportPlay {
    background: qradialgradient(cx:0.5, cy:0.35, radius:0.75,
        stop:0 #2bf07c, stop:0.55 #1DB954, stop:1 #128a3d);
    color: #06170d;
    border: 1px solid #0e6e34;
    border-radius: 28px;
    min-width: 57px; min-height: 57px;
    font-size: 22pt;
    font-weight: 800;
}
QToolButton#transportPlay:hover {
    background: qradialgradient(cx:0.5, cy:0.35, radius:0.75,
        stop:0 #38ff86, stop:0.55 #1ED760, stop:1 #169a45);
}
QToolButton#transportPlay:pressed {
    background: qradialgradient(cx:0.5, cy:0.55, radius:0.75,
        stop:0 #1DB954, stop:1 #0e6e34);
}

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
