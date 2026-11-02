# garud360/ui/pages/settings_page.py
"""Settings console: every tunable value with defaults, explanations and a built-in guide."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from garud360.config import settings_schema as sc
from garud360.db.repositories import RepoError
from garud360.ui.context import AppContext
from garud360.ui.theme import C
from garud360.ui.util import confirm, error_box, info_box, run_task
from garud360.ui.widgets.settings_form import SettingsForm

TAB_GROUPS = [
    ("Model && Hardware", [sc.G_MODEL]),
    ("Detection", [sc.G_DETECT, sc.G_ROI]),
    ("Cameras", [sc.G_CAMERA]),
    ("Crane && PLC", [sc.G_INTERLOCK, sc.G_PLC]),
    ("Alerts", [sc.G_ALERT]),
    ("Storage && Display", [sc.G_SNAP, sc.G_UI]),
]


def _verify_model(values: dict) -> str:
    """Load the configured model once (downloads the weights on first use). Runs on a worker thread."""
    from garud360.core.detection.engine import ModelConfig, YoloBackend
    cfg = ModelConfig.from_settings(values)
    backend = YoloBackend(cfg)
    backend.load()
    backend.close()
    return f"Model '{cfg.weights()}' loaded successfully."


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self._task = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        head = QHBoxLayout()
        h = QLabel("Settings")
        h.setObjectName("h1")
        head.addWidget(h)
        head.addStretch(1)
        self.verify = QPushButton("Download / verify model")
        self.verify.setToolTip("Loads the selected YOLO model once. The first time it is downloaded (internet needed).")
        self.verify.clicked.connect(self._verify)
        siren = QPushButton("Test siren (3 s)")
        siren.clicked.connect(lambda: self.ctx.runtime.siren.test(3.0))
        reset = QPushButton("Restore all defaults")
        reset.clicked.connect(self._reset)
        self.save = QPushButton("Save settings")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self._save)
        for b in (self.verify, siren, reset, self.save):
            head.addWidget(b)
        lay.addLayout(head)
        self.note = QLabel("These are the global defaults for every space. Spaces can override the settings marked "
                           "'per space' (Spaces > Edit > Detection & Behaviour). Changes apply to running spaces "
                           "immediately; model changes reload the detector.")
        self.note.setWordWrap(True)
        self.note.setProperty("muted", True)
        lay.addWidget(self.note)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.forms: list[SettingsForm] = []
        self._build()

    def _build(self) -> None:
        self.tabs.clear()
        self.forms.clear()
        values = self.ctx.settings.all()
        for title, groups in TAB_GROUPS:
            keys = [s.key for g in groups for s in sc.SETTINGS if s.group == g]
            form = SettingsForm(keys, values)
            self.forms.append(form)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            inner = QWidget()
            il = QVBoxLayout(inner)
            il.addWidget(form)
            sa.setWidget(inner)
            self.tabs.addTab(sa, title)
        guide = QTextBrowser()
        guide.setOpenExternalLinks(True)
        guide.setMarkdown(sc.guide_markdown().split("\n", 1)[1])
        self.tabs.addTab(guide, "Settings guide")
        read_only = not self.ctx.is_admin
        for f in self.forms:
            f.setEnabled(not read_only)
        self.save.setEnabled(not read_only)
        if read_only:
            self.status.setText("Only administrators can change settings.")

    def _msg(self, text: str, ok: bool = True) -> None:
        self.status.setText(f"<span style='color:{C['ok'] if ok else C['crit']}'>{text}</span>")

    def _save(self) -> None:
        changes: dict = {}
        for f in self.forms:
            changes.update(f.collect())
        try:
            self.ctx.settings.update(changes)
        except RepoError as exc:
            self._msg(str(exc), False)
            error_box(self, "Settings not saved", str(exc))
            return
        self.ctx.events.log_audit(self.ctx.username, "settings_saved")
        self.ctx.runtime.engine.request_reload()
        self._msg("Settings saved.")
        QTimer.singleShot(4000, lambda: self.status.setText(""))

    def _reset(self) -> None:
        if confirm(self, "Restore defaults", "Reset ALL global settings to their factory defaults?\n"
                                               "(Per-space overrides are kept.)", True):
            self.ctx.settings.reset_all()
            self.ctx.events.log_audit(self.ctx.username, "settings_reset")
            self._build()
            self._msg("Defaults restored.")

    def _verify(self) -> None:
        vals = self.ctx.settings.all()
        for f in self.forms:
            vals.update(f.collect())
        try:
            vals = {k: sc.coerce(k, v) for k, v in vals.items()}
        except ValueError as exc:
            error_box(self, "Invalid value", str(exc))
            return
        self.verify.setEnabled(False)
        self._msg("Loading model ... (the first download can take a minute)")
        self._task = run_task(_verify_model, self._verified, self._verify_failed, vals)

    def _verified(self, msg: object) -> None:
        self.verify.setEnabled(True)
        self._msg(str(msg))

    def _verify_failed(self, msg: str) -> None:
        self.verify.setEnabled(True)
        self._msg(f"Model could not be loaded: {msg}", False)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if not self.forms[0].isEnabled() and self.ctx.is_admin:
            self._build()
