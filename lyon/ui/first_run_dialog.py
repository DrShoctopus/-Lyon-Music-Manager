"""First-run setup dialog."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPushButton, QVBoxLayout, QWidget,
)

from ..core.diagnostics import run_dependency_checks, summarize_dependency_checks
from ..core.settings import Settings, normalize_library_paths
from .diagnostics_dialog import DiagnosticsDialog


class FirstRunDialog(QDialog):
    """Collect essential setup choices and highlight missing dependencies."""

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Sea Lyon Media Manager")
        self.resize(680, 480)
        self.result_settings = replace(settings)
        self.result_settings.library_paths = normalize_library_paths(settings.library_paths)
        self.skipped = False
        self._checks = run_dependency_checks()

        title = QLabel("Let’s finish setting up Sea Lyon Media Manager")
        title.setObjectName("sectionTitle")

        intro = QLabel(
            "Choose where ripped music should go, add any existing music folders, "
            "and review optional runtime components for ripping, CD detection, playback, and YouTube."
        )
        intro.setWordWrap(True)

        root_row = QHBoxLayout()
        self.root_edit = QLineEdit(settings.music_root)
        browse_root = QPushButton("Browse...")
        browse_root.clicked.connect(self._browse_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(browse_root)

        root_label = QLabel("Music folder for new rips:")
        root_label.setObjectName("formLabel")

        folders_label = QLabel("Library folders to scan:")
        folders_label.setObjectName("formLabel")
        self.library_paths = QListWidget()
        for folder in normalize_library_paths(settings.library_paths):
            self.library_paths.addItem(folder)

        folder_buttons = QHBoxLayout()
        add_folder = QPushButton("Add Folder...")
        remove_folder = QPushButton("Remove Selected")
        add_folder.clicked.connect(self._add_library_folder)
        remove_folder.clicked.connect(self._remove_selected_library_folder)
        folder_buttons.addWidget(add_folder)
        folder_buttons.addWidget(remove_folder)
        folder_buttons.addStretch(1)

        diag_summary = QLabel(summarize_dependency_checks(self._checks))
        diag_summary.setWordWrap(True)
        diag_summary.setObjectName("mutedText")
        diagnostics_btn = QPushButton("View Runtime Diagnostics")
        diagnostics_btn.clicked.connect(self._show_diagnostics)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save Setup")
        skip_btn = buttons.addButton("Skip Setup", QDialogButtonBox.ActionRole)
        skip_btn.clicked.connect(self._skip_setup)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(root_label)
        layout.addLayout(root_row)
        layout.addWidget(folders_label)
        layout.addWidget(self.library_paths, 1)
        layout.addLayout(folder_buttons)
        layout.addWidget(diag_summary)
        layout.addWidget(diagnostics_btn, alignment=Qt.AlignLeft)
        layout.addWidget(buttons)

    def _browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose music folder", self.root_edit.text())
        if folder:
            self.root_edit.setText(folder)

    def _add_library_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add library folder", self.root_edit.text())
        if folder and not self._contains_folder(folder):
            self.library_paths.addItem(folder)

    def _remove_selected_library_folder(self) -> None:
        for item in self.library_paths.selectedItems():
            self.library_paths.takeItem(self.library_paths.row(item))

    def _contains_folder(self, folder: str) -> bool:
        return any(self.library_paths.item(row).text() == folder for row in range(self.library_paths.count()))

    def _show_diagnostics(self) -> None:
        dlg = DiagnosticsDialog(self._checks, self)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _skip_setup(self) -> None:
        self.skipped = True
        self.result_settings.first_run_completed = True
        self.accept()

    def _accept(self) -> None:
        self.result_settings.music_root = self.root_edit.text().strip() or self.result_settings.music_root
        self.result_settings.library_paths = normalize_library_paths([
            self.library_paths.item(row).text()
            for row in range(self.library_paths.count())
        ])
        if self.result_settings.music_root not in self.result_settings.library_paths:
            self.result_settings.library_paths.insert(0, self.result_settings.music_root)
        self.result_settings.first_run_completed = True
        self.accept()
