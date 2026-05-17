"""Dialog for creating and editing smart playlists."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.smart_playlist import (
    FIELDS, FIELD_MAP, OPS_FOR_TYPE, ORDER_BY_OPTIONS,
    Rule, SmartPlaylistSpec, spec_from_json, spec_to_json,
)


class _RuleRow(QWidget):
    def __init__(self, rule: Rule | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.field_cb = QComboBox()
        self.field_cb.blockSignals(True)
        for display, col, _ in FIELDS:
            self.field_cb.addItem(display, col)
        self.field_cb.blockSignals(False)

        self.op_cb = QComboBox()

        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("value")
        self.value_edit.setMinimumWidth(120)

        self.value2_edit = QLineEdit()
        self.value2_edit.setPlaceholderText("and")
        self.value2_edit.setMinimumWidth(70)
        self.value2_edit.setVisible(False)

        self.remove_btn = QPushButton("−")
        self.remove_btn.setFixedWidth(28)
        self.remove_btn.setToolTip("Remove rule")

        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(6)
        hl.addWidget(self.field_cb)
        hl.addWidget(self.op_cb)
        hl.addWidget(self.value_edit, 1)
        hl.addWidget(self.value2_edit)
        hl.addWidget(self.remove_btn)

        # Connect after layout so signals don't fire during construction
        self.field_cb.currentIndexChanged.connect(self._on_field_changed)
        self.op_cb.currentIndexChanged.connect(self._on_op_changed)

        # Seed ops for the default field (index 0), then apply rule values
        self._populate_ops(self.field_cb.currentData())

        if rule is not None:
            fi = self.field_cb.findData(rule.field)
            if fi >= 0:
                self.field_cb.setCurrentIndex(fi)
            oi = self.op_cb.findData(rule.op)
            if oi >= 0:
                self.op_cb.setCurrentIndex(oi)
            self.value_edit.setText(rule.value)
            self.value2_edit.setText(rule.value2)
            self._on_op_changed(self.op_cb.currentIndex())

    def _populate_ops(self, col: str | None) -> None:
        finfo = FIELD_MAP.get(col or "title")
        vtype = finfo[2] if finfo else "text"
        ops = OPS_FOR_TYPE.get(vtype, OPS_FOR_TYPE["text"])

        old_op = self.op_cb.currentData()
        self.op_cb.blockSignals(True)
        self.op_cb.clear()
        for key, label in ops:
            self.op_cb.addItem(label, key)
        ri = self.op_cb.findData(old_op)
        if ri >= 0:
            self.op_cb.setCurrentIndex(ri)
        self.op_cb.blockSignals(False)

        # Update value placeholder based on type
        if vtype == "int":
            self.value_edit.setPlaceholderText("number")
        elif vtype == "bool":
            self.value_edit.setPlaceholderText("true / false")
        else:
            self.value_edit.setPlaceholderText("value")

        self._on_op_changed(self.op_cb.currentIndex())

    def _on_field_changed(self, _: int) -> None:
        self._populate_ops(self.field_cb.currentData())

    def _on_op_changed(self, _: int) -> None:
        self.value2_edit.setVisible(self.op_cb.currentData() == "between")

    def to_rule(self) -> Rule:
        return Rule(
            field=self.field_cb.currentData() or "title",
            op=self.op_cb.currentData() or "contains",
            value=self.value_edit.text(),
            value2=self.value2_edit.text() if self.value2_edit.isVisible() else "",
        )


class SmartPlaylistDialog(QDialog):
    """Create or edit a smart playlist."""

    def __init__(
        self,
        name: str = "",
        rules_json: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Smart Playlist" if rules_json else "New Smart Playlist")
        self.setMinimumWidth(580)
        self._result_spec: SmartPlaylistSpec | None = None
        self._result_name: str = ""

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # Name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(name)
        self._name_edit.setPlaceholderText("Playlist name")
        name_row.addWidget(self._name_edit, 1)
        outer.addLayout(name_row)

        # Match row
        match_row = QHBoxLayout()
        match_row.addWidget(QLabel("Match"))
        self._match_cb = QComboBox()
        self._match_cb.addItem("All", "all")
        self._match_cb.addItem("Any", "any")
        match_row.addWidget(self._match_cb)
        match_row.addWidget(QLabel("of the following rules:"))
        match_row.addStretch(1)
        outer.addLayout(match_row)

        # Rules scroll area
        self._rules_container = QWidget()
        self._rules_vl = QVBoxLayout(self._rules_container)
        self._rules_vl.setContentsMargins(0, 0, 0, 0)
        self._rules_vl.setSpacing(2)
        self._rules_vl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self._rules_container)
        scroll.setMinimumHeight(150)
        outer.addWidget(scroll, 1)

        add_btn = QPushButton("+ Add Rule")
        add_btn.clicked.connect(lambda: self._add_rule())
        outer.addWidget(add_btn, 0, Qt.AlignLeft)

        # Limit row
        limit_row = QHBoxLayout()
        self._limit_check = QCheckBox("Limit to")
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(1, 10000)
        self._limit_spin.setValue(100)
        self._limit_spin.setEnabled(False)
        self._limit_check.toggled.connect(self._limit_spin.setEnabled)
        limit_row.addWidget(self._limit_check)
        limit_row.addWidget(self._limit_spin)
        limit_row.addWidget(QLabel("tracks"))
        limit_row.addStretch(1)
        outer.addLayout(limit_row)

        # Order by row
        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("Order by"))
        self._order_cb = QComboBox()
        for col, label in ORDER_BY_OPTIONS:
            self._order_cb.addItem(label, col)
        self._order_dir_cb = QComboBox()
        self._order_dir_cb.addItem("Ascending", False)
        self._order_dir_cb.addItem("Descending", True)
        order_row.addWidget(self._order_cb)
        order_row.addWidget(self._order_dir_cb)
        order_row.addStretch(1)
        outer.addLayout(order_row)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        # Populate from existing spec
        if rules_json:
            spec = spec_from_json(rules_json)
            mi = self._match_cb.findData(spec.match)
            if mi >= 0:
                self._match_cb.setCurrentIndex(mi)
            for rule in spec.rules:
                self._add_rule(rule)
            if spec.limit > 0:
                self._limit_check.setChecked(True)
                self._limit_spin.setValue(spec.limit)
            oi = self._order_cb.findData(spec.order_by)
            if oi >= 0:
                self._order_cb.setCurrentIndex(oi)
            self._order_dir_cb.setCurrentIndex(1 if spec.order_desc else 0)
        else:
            self._add_rule()  # start with one empty rule

    def _add_rule(self, rule: Rule | None = None) -> None:
        row = _RuleRow(rule, self._rules_container)
        row.remove_btn.clicked.connect(lambda: self._remove_rule(row))
        # Insert before the trailing stretch
        self._rules_vl.insertWidget(self._rules_vl.count() - 1, row)

    def _remove_rule(self, row: _RuleRow) -> None:
        self._rules_vl.removeWidget(row)
        row.deleteLater()

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            return
        rows = [
            w
            for i in range(self._rules_vl.count())
            if isinstance(w := self._rules_vl.itemAt(i).widget(), _RuleRow)
        ]
        self._result_name = name
        self._result_spec = SmartPlaylistSpec(
            match=self._match_cb.currentData() or "all",
            rules=[r.to_rule() for r in rows],
            limit=self._limit_spin.value() if self._limit_check.isChecked() else 0,
            order_by=self._order_cb.currentData() or "title",
            order_desc=bool(self._order_dir_cb.currentData()),
        )
        self.accept()

    @property
    def playlist_name(self) -> str:
        return self._result_name

    @property
    def spec(self) -> SmartPlaylistSpec | None:
        return self._result_spec
