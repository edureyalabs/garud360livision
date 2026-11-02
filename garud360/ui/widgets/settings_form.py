# garud360/ui/widgets/settings_form.py
"""Schema-driven settings editor used by the Settings page and by the per-space override tab."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from garud360.config import settings_schema as sc
from garud360.ui.theme import C


def _fmt_default(d: sc.SettingDef) -> str:
    if d.kind == "bool":
        return "ON" if d.default else "OFF"
    if d.default == "":
        return "(empty)"
    return f"{d.default}{(' ' + d.unit) if d.unit else ''}"


class SettingRow(QFrame):
    """One setting: label, editor, default, reset, expandable 'what happens if I change it' help."""

    def __init__(self, d: sc.SettingDef, override_mode: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.d = d
        self.override_mode = override_mode
        self.setObjectName("panel")
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(12)
        self.use = QCheckBox()
        self.use.setToolTip("Tick to override the global value for this space")
        title = QLabel(d.label)
        title.setStyleSheet("font-weight: 600;")
        self.editor = self._make_editor()
        self.default_lbl = QLabel(f"Default: {_fmt_default(d)}")
        self.default_lbl.setProperty("muted", True)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setFixedWidth(60)
        self.reset_btn.clicked.connect(lambda: self.set_value(d.default))
        self.more = QToolButton()
        self.more.setText("How it works ▾")
        self.more.setCheckable(True)
        self.more.setStyleSheet(f"QToolButton {{ border: none; color: {C['accent_hi']}; }}")
        self.help = QLabel(f"{d.help}")
        self.help.setWordWrap(True)
        self.help.setProperty("muted", True)
        effects = ""
        if d.increase:
            effects += f"<b style='color:{C['ok']}'>Raise / ON:</b> {d.increase}<br>"
        if d.decrease:
            effects += f"<b style='color:{C['warn']}'>Lower / OFF:</b> {d.decrease}"
        self.effects = QLabel(effects)
        self.effects.setWordWrap(True)
        self.effects.setTextFormat(Qt.TextFormat.RichText)
        self.effects.setVisible(False)
        self.more.toggled.connect(self.effects.setVisible)
        col = 0
        if override_mode:
            grid.addWidget(self.use, 0, 0)
            col = 1
        grid.addWidget(title, 0, col)
        grid.addWidget(self.editor, 0, col + 1)
        grid.addWidget(self.default_lbl, 0, col + 2)
        grid.addWidget(self.reset_btn, 0, col + 3)
        grid.addWidget(self.help, 1, col, 1, 4)
        grid.addWidget(self.more, 2, col, 1, 2, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.effects, 3, col, 1, 4)
        grid.setColumnStretch(col, 3)
        grid.setColumnStretch(col + 1, 2)
        if override_mode:
            self.use.toggled.connect(self._sync_enabled)
            self._sync_enabled(False)

    def _make_editor(self) -> QWidget:
        d = self.d
        if d.kind == "bool":
            w: QWidget = QCheckBox("Enabled")
        elif d.kind == "int":
            w = QSpinBox()
            w.setRange(int(d.minimum if d.minimum is not None else -10**9), int(d.maximum if d.maximum is not None else 10**9))
            w.setSingleStep(int(d.step or 1))
            if d.unit:
                w.setSuffix(f" {d.unit}")
        elif d.kind == "float":
            w = QDoubleSpinBox()
            step = d.step or 0.1
            w.setDecimals(2 if step < 0.1 else 1)
            w.setRange(d.minimum if d.minimum is not None else -1e9, d.maximum if d.maximum is not None else 1e9)
            w.setSingleStep(step)
            if d.unit:
                w.setSuffix(f" {d.unit}")
        elif d.kind == "choice":
            w = QComboBox()
            w.addItems(list(d.choices))
            w.setEditable(d.editable_choice)
        else:
            w = QLineEdit()
            w.setPlaceholderText("(empty)")
        w.setMinimumWidth(150)
        return w

    def _sync_enabled(self, on: bool) -> None:
        self.editor.setEnabled(on)
        self.reset_btn.setEnabled(on)

    def set_value(self, v: Any) -> None:
        e, d = self.editor, self.d
        if d.kind == "bool":
            e.setChecked(bool(v))                 # type: ignore[attr-defined]
        elif d.kind in ("int", "float"):
            e.setValue(v)                         # type: ignore[attr-defined]
        elif d.kind == "choice":
            e.setCurrentText(str(v))              # type: ignore[attr-defined]
        else:
            e.setText(str(v))                     # type: ignore[attr-defined]

    def value(self) -> Any:
        e, d = self.editor, self.d
        if d.kind == "bool":
            return e.isChecked()                  # type: ignore[attr-defined]
        if d.kind in ("int", "float"):
            return e.value()                      # type: ignore[attr-defined]
        if d.kind == "choice":
            return e.currentText()                # type: ignore[attr-defined]
        return e.text()                           # type: ignore[attr-defined]


class SettingsForm(QWidget):
    """Rows for a list of settings. In override mode each row has a 'use override' tick box."""

    def __init__(self, keys: list[str], values: dict[str, Any], override_mode: bool = False,
                 overrides: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.override_mode = override_mode
        self.rows: dict[str, SettingRow] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        current_group = None
        for key in keys:
            d = sc.BY_KEY[key]
            if d.group != current_group:
                current_group = d.group
                head = QLabel(d.group)
                head.setObjectName("h2")
                head.setContentsMargins(0, 8, 0, 0)
                lay.addWidget(head)
            row = SettingRow(d, override_mode)
            row.set_value((overrides or {}).get(key, values.get(key, d.default)))
            if override_mode:
                row.use.setChecked(key in (overrides or {}))
            self.rows[key] = row
            lay.addWidget(row)
        lay.addStretch(1)

    def collect(self) -> dict[str, Any]:
        """Values to save (override mode: only the ticked rows)."""
        out = {}
        for k, r in self.rows.items():
            if self.override_mode and not r.use.isChecked():
                continue
            out[k] = r.value()
        return out
