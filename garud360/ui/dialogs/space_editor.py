# garud360/ui/dialogs/space_editor.py
"""Create / edit a space: general info, cameras, output (PLC) channel and per-space detection overrides."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from garud360.config import defaults as cfg
from garud360.config import settings_schema as sc
from garud360.core.camera.source import describe
from garud360.core.models import SOURCE_LABELS, Camera, Space
from garud360.core.plc import registry
from garud360.core.plc.base import POLARITY_BLOCK_HIGH, POLARITY_PERMIT_HIGH, FieldDef, PlcConfig
from garud360.db.repositories import RepoError
from garud360.ui.context import AppContext
from garud360.ui.dialogs.camera_dialogs import CameraEditorDialog
from garud360.ui.theme import C
from garud360.ui.util import app_icon, error_box, run_task
from garud360.ui.widgets.settings_form import SettingsForm


class PlcForm(QWidget):
    """Output channel configuration; the extra fields are generated from the chosen driver."""
    test_done = Signal(bool, str)

    def __init__(self, plc: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._extra_widgets: dict[str, QWidget] = {}
        self._task = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.type = QComboBox()
        for key, drv in registry.DRIVERS.items():
            self.type.addItem(drv.LABEL, key)
        self.host = QLineEdit()
        self.host.setPlaceholderText("PLC IP address, e.g. 192.168.0.10")
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("default")
        self.permit = QLineEdit()
        self.polarity = QComboBox()
        self.polarity.addItem("Run permissive: bit = 1 lets the crane move, 0 = BLOCK (holder knob released)",
                              POLARITY_PERMIT_HIGH)
        self.polarity.addItem("Halt command: bit = 1 = BLOCK, 0 lets the crane move", POLARITY_BLOCK_HIGH)
        self.heartbeat = QLineEdit()
        self.status = QLineEdit()
        self.load = QLineEdit()
        self.reset = QLineEdit()
        self.pause = QLineEdit()
        form.addRow("Channel type", self.type)
        self.host_row = (QLabel("Host / IP"), self.host)
        form.addRow(*self.host_row)
        self.port_row = (QLabel("Port"), self.port)
        form.addRow(*self.port_row)
        form.addRow("Crane output address", self.permit)
        form.addRow("Output logic", self.polarity)
        self.extra_form = QFormLayout()
        lay.addLayout(form)
        lay.addLayout(self.extra_form)
        opt = QLabel("Optional addresses (leave empty if not wired)")
        opt.setObjectName("h2")
        lay.addWidget(opt)
        f2 = QFormLayout()
        f2.addRow("Heartbeat output (toggles)", self.heartbeat)
        f2.addRow("Blocked lamp / horn output", self.status)
        f2.addRow("Load-present input", self.load)
        f2.addRow("Reset input (crane remote)", self.reset)
        f2.addRow("Pause input (attach / detach load)", self.pause)
        lay.addLayout(f2)
        self.help = QLabel("")
        self.help.setWordWrap(True)
        self.help.setProperty("muted", True)
        lay.addWidget(self.help)
        row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection (read only)")
        self.test_btn.clicked.connect(self._test)
        self.test_lbl = QLabel("")
        self.test_lbl.setWordWrap(True)
        row.addWidget(self.test_btn)
        row.addWidget(self.test_lbl, 1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.type.currentIndexChanged.connect(self._type_changed)
        self.test_done.connect(self._on_test)
        self._load(plc)

    def _load(self, plc: dict[str, Any]) -> None:
        c = PlcConfig.from_dict(plc)
        idx = self.type.findData(c.type if c.type in registry.DRIVERS else "simulated")
        self.type.setCurrentIndex(idx)
        self._type_changed()
        self.host.setText(c.host)
        self.port.setValue(c.port)
        self.permit.setText(c.permit_address)
        self.polarity.setCurrentIndex(max(0, self.polarity.findData(c.polarity)))
        self.heartbeat.setText(c.heartbeat_address)
        self.status.setText(c.status_address)
        self.load.setText(c.load_present_address)
        self.reset.setText(c.reset_address)
        self.pause.setText(c.pause_address)
        for k, w in self._extra_widgets.items():
            self._set_extra(w, c.extras.get(k))

    def _type_changed(self) -> None:
        drv = registry.DRIVERS[self.type.currentData()]
        sim = drv.TYPE == "simulated"
        for w in (*self.host_row, *self.port_row):
            w.setVisible(not sim)
        self.port.setSpecialValueText(f"default ({drv.DEFAULT_PORT})" if drv.DEFAULT_PORT else "default")
        self.permit.setPlaceholderText(drv.EXAMPLE_PERMIT)
        while self.extra_form.rowCount():
            self.extra_form.removeRow(0)
        self._extra_widgets.clear()
        for fd in drv.EXTRA_FIELDS:
            w = self._make_extra(fd)
            self._extra_widgets[fd.key] = w
            self.extra_form.addRow(fd.label, w)
            self._set_extra(w, fd.default)
            if fd.help:
                w.setToolTip(fd.help)
        self.help.setText(f"{drv.ADDRESS_HELP}\n{drv.NOTES}")
        for w in (self.permit, self.polarity, self.heartbeat, self.status, self.load, self.reset, self.pause):
            w.setEnabled(not sim)
        self.test_btn.setEnabled(not sim)
        self.test_lbl.setText("")

    @staticmethod
    def _make_extra(fd: FieldDef) -> QWidget:
        if fd.kind == "int":
            w = QSpinBox()
            w.setRange(fd.minimum, fd.maximum)
            return w
        if fd.kind == "bool":
            return QCheckBox()
        if fd.kind == "choice":
            c = QComboBox()
            c.addItems(list(fd.choices))
            return c
        return QLineEdit()

    @staticmethod
    def _set_extra(w: QWidget, v: Any) -> None:
        if isinstance(w, QSpinBox):
            w.setValue(int(v or 0))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(v))
        elif isinstance(w, QComboBox):
            if v is not None:
                w.setCurrentText(str(v))
        elif isinstance(w, QLineEdit):
            w.setText("" if v is None else str(v))

    @staticmethod
    def _get_extra(w: QWidget) -> Any:
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text().strip() if isinstance(w, QLineEdit) else None

    def collect(self) -> dict[str, Any]:
        return {"type": self.type.currentData(), "host": self.host.text().strip(), "port": self.port.value(),
                "permit_address": self.permit.text().strip(), "polarity": self.polarity.currentData(),
                "heartbeat_address": self.heartbeat.text().strip(), "status_address": self.status.text().strip(),
                "load_present_address": self.load.text().strip(), "reset_address": self.reset.text().strip(),
                "pause_address": self.pause.text().strip(),
                "extras": {k: self._get_extra(w) for k, w in self._extra_widgets.items()}}

    def _test(self) -> None:
        cfgd = self.collect()
        self.test_btn.setEnabled(False)
        self.test_lbl.setText("Testing ...")
        self._task = run_task(registry.check_connection, lambda r: self.test_done.emit(*r),
                              lambda m: self.test_done.emit(False, m), cfgd)

    def _on_test(self, ok: bool, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_lbl.setText(f"<span style='color:{C['ok'] if ok else C['crit']}'>{msg}</span>")


class SpaceEditorDialog(QDialog):
    def __init__(self, ctx: AppContext, space: Space | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.space = deepcopy(space) if space else Space(0, "", plc_config={"type": "simulated"})
        self.saved: Space | None = None
        self.setWindowTitle("Edit space" if space else "New space")
        self.setWindowIcon(app_icon())
        self.resize(760, 680)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # ---- General
        g = QWidget()
        f = QFormLayout(g)
        self.name = QLineEdit(self.space.name)
        self.name.setMaxLength(60)
        self.name.setPlaceholderText("e.g. Bay 3 - Steel store")
        self.desc = QPlainTextEdit(self.space.description)
        self.desc.setFixedHeight(80)
        self.auto = QCheckBox("Start this space automatically when the application opens")
        self.auto.setChecked(self.space.auto_start)
        f.addRow("Space name", self.name)
        f.addRow("Description", self.desc)
        f.addRow("", self.auto)
        tabs.addTab(g, "General")

        # ---- Cameras
        c = QWidget()
        cl = QVBoxLayout(c)
        self.cam_count = QLabel()
        cl.addWidget(self.cam_count)
        self.cam_list = QListWidget()
        self.cam_list.itemDoubleClicked.connect(lambda _i: self._edit_camera())
        cl.addWidget(self.cam_list, 1)
        row = QHBoxLayout()
        for text, fn in (("Add camera", self._add_camera), ("Edit", self._edit_camera), ("Remove", self._remove_camera),
                         ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            if text == "Add camera":
                b.setObjectName("primary")
                self.add_btn = b
        row.addStretch(1)
        cl.addLayout(row)
        tabs.addTab(c, "Cameras")

        # ---- Output
        self.plc_form = PlcForm(self.space.plc_config)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.plc_form)
        tabs.addTab(sa, "Output channel (PLC)")

        # ---- Overrides
        glob = ctx.settings.all()
        self.over_form = SettingsForm(list(sc.PER_SPACE_KEYS), glob, override_mode=True, overrides=self.space.overrides)
        sa2 = QScrollArea()
        sa2.setWidgetResizable(True)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.addWidget(QLabel("Tick a setting to use a different value for this space only. Un-ticked settings follow the "
                            "global Settings page."))
        il.itemAt(0).widget().setWordWrap(True)
        il.addWidget(self.over_form)
        sa2.setWidget(inner)
        tabs.addTab(sa2, "Detection && Behaviour")

        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {C['crit']};")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save space")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)
        self._refresh_cams()

    # ---- cameras --------------------------------------------------------------------------
    def _refresh_cams(self) -> None:
        self.cam_list.clear()
        for cam in self.space.cameras:
            roi = " | zone set" if cam.roi else ""
            off = "" if cam.enabled else "  [disabled]"
            it = QListWidgetItem(f"{cam.name}  -  {SOURCE_LABELS.get(cam.source_type, cam.source_type)}  "
                                 f"({describe(cam.source_type, cam.source_config)}){roi}{off}")
            self.cam_list.addItem(it)
        n = len(self.space.cameras)
        self.cam_count.setText(f"{n} / {cfg.MAX_CAMERAS_PER_SPACE} cameras")
        self.add_btn.setEnabled(n < cfg.MAX_CAMERAS_PER_SPACE)

    def _timeout(self) -> float:
        return float(self.ctx.settings.all()["connect_timeout_s"])

    def _add_camera(self) -> None:
        dlg = CameraEditorDialog(None, self._timeout(), self)
        if dlg.exec() and dlg.result_camera:
            self.space.cameras.append(dlg.result_camera)
            self._refresh_cams()

    def _edit_camera(self) -> None:
        i = self.cam_list.currentRow()
        if i < 0:
            return
        dlg = CameraEditorDialog(self.space.cameras[i], self._timeout(), self)
        if dlg.exec() and dlg.result_camera:
            self.space.cameras[i] = dlg.result_camera
            self._refresh_cams()
            self.cam_list.setCurrentRow(i)

    def _remove_camera(self) -> None:
        i = self.cam_list.currentRow()
        if i >= 0:
            del self.space.cameras[i]
            self._refresh_cams()

    def _move(self, d: int) -> None:
        i = self.cam_list.currentRow()
        j = i + d
        if i >= 0 and 0 <= j < len(self.space.cameras):
            cams = self.space.cameras
            cams[i], cams[j] = cams[j], cams[i]
            self._refresh_cams()
            self.cam_list.setCurrentRow(j)

    # ---- save ---------------------------------------------------------------------------------
    def _save(self) -> None:
        plc = self.plc_form.collect()
        errs = registry.validate(plc)
        if errs:
            self.error.setText(f"Output channel: {errs[0]}")
            return
        sp = self.space
        sp.name, sp.description = self.name.text(), self.desc.toPlainText()
        sp.auto_start, sp.plc_config = self.auto.isChecked(), plc
        sp.overrides = self.over_form.collect()
        try:
            self.saved = self.ctx.spaces.save(sp)
        except RepoError as exc:
            self.error.setText(str(exc))
            return
        self.ctx.events.log_audit(self.ctx.username, "space_saved", self.saved.name)
        self.accept()
