"""User-facing runtime dependency diagnostics."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.diagnostics import DependencyCheck, DiagnosticStatus, run_dependency_checks, summarize_dependency_checks
from .theme import STATUS_ERROR, STATUS_OK, STATUS_WARNING


_STATUS_COLORS = {
    DiagnosticStatus.OK: QColor(STATUS_OK),
    DiagnosticStatus.WARNING: QColor(STATUS_WARNING),
    DiagnosticStatus.MISSING: QColor(STATUS_ERROR),
}


class DiagnosticsDialog(QDialog):
    """Dialog that explains optional runtime dependency readiness."""

    def __init__(self, checks: list[DependencyCheck] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Runtime Diagnostics")
        self.resize(860, 360)
        self.checks = checks or run_dependency_checks()

        summary = QLabel(summarize_dependency_checks(self.checks))
        summary.setWordWrap(True)
        summary.setObjectName("dialogSummary")

        self.table = QTableWidget(len(self.checks), 4, self)
        self.table.setHorizontalHeaderLabels(["Component", "Status", "Details", "How to fix"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self._populate()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.resizeRowsToContents()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        for row, check in enumerate(self.checks):
            values = [check.name, check.status.value, check.detail, check.fix]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 1:
                    item.setForeground(_STATUS_COLORS[check.status])
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
