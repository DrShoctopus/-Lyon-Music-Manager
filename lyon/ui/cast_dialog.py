"""Cast-to-device dialog: discover DLNA renderers and initiate/stop casting."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.dlna_renderer_discovery import RendererDevice, RendererDiscovery


class CastDialog(QDialog):
    """Show discovered DLNA renderers and let the user cast to one."""

    cast_requested = Signal(object)   # RendererDevice
    stop_requested = Signal()

    def __init__(
        self,
        on_cast: Callable[[RendererDevice], None],
        on_stop: Callable[[], None],
        is_casting: bool = False,
        cast_target_name: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Cast to Device")
        self.resize(420, 340)
        self.setMinimumSize(320, 260)

        self._on_cast = on_cast
        self._on_stop = on_stop
        self._devices: list[RendererDevice] = []
        self._discovery: RendererDiscovery | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Status / cast-target label
        self._status_label = QLabel()
        self._status_label.setObjectName("castStatusLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # Device list
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._cast_selected)
        layout.addWidget(self._list)

        # Buttons
        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._start_scan)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch(1)

        self._cast_btn = QPushButton("Cast to Selected")
        self._cast_btn.setEnabled(False)
        self._cast_btn.clicked.connect(self._cast_selected)
        btn_row.addWidget(self._cast_btn)

        self._stop_btn = QPushButton("Stop Casting")
        self._stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self._stop_btn)

        layout.addLayout(btn_row)

        self._list.currentRowChanged.connect(self._on_selection_changed)

        self._apply_cast_state(is_casting, cast_target_name)
        self._start_scan()

    # ------------------------------------------------------------------
    # Public interface (called from MainWindow)
    # ------------------------------------------------------------------

    def update_cast_state(self, is_casting: bool, target_name: str = "") -> None:
        self._apply_cast_state(is_casting, target_name)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_cast_state(self, is_casting: bool, target_name: str) -> None:
        self._stop_btn.setVisible(is_casting)
        if is_casting:
            self._status_label.setText(f"Casting to: {target_name}")
        else:
            self._status_label.setText("")

    def _start_scan(self) -> None:
        if self._discovery is not None and self._discovery.isRunning():
            return
        self._list.clear()
        self._devices = []
        self._cast_btn.setEnabled(False)
        self._status_label.setText("Scanning for devices…")
        self._refresh_btn.setEnabled(False)

        self._discovery = RendererDiscovery(timeout=3.0, parent=self)
        self._discovery.discovered.connect(self._on_discovered)
        self._discovery.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._discovery.start()

    def _on_discovered(self, devices: list[RendererDevice]) -> None:
        self._devices = devices
        self._list.clear()

        if not devices:
            self._status_label.setText("No devices found. Make sure DLNA sharing is enabled in Settings.")
            return

        self._status_label.setText("")
        for device in devices:
            item = QListWidgetItem(device.friendly_name)
            item.setToolTip(device.location_url)
            self._list.addItem(item)

        self._list.setCurrentRow(0)

    def _on_selection_changed(self, row: int) -> None:
        self._cast_btn.setEnabled(0 <= row < len(self._devices))

    def _cast_selected(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._devices):
            self._on_cast(self._devices[row])

    def _stop(self) -> None:
        self._on_stop()

    def closeEvent(self, ev) -> None:
        if self._discovery is not None and self._discovery.isRunning():
            self._discovery.stop()
            if not self._discovery.wait(4000):
                ev.ignore()
                return
        super().closeEvent(ev)
