# garud360/ui/pages/dashboard.py
"""Dashboard: summary tiles, filterable space cards, and the per-space live view (cameras + crane simulation)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from garud360.core.models import Space
from garud360.core.runtime import SpaceStartError
from garud360.core.space.interlock import Status
from garud360.core.space.monitor import SpaceSnapshot
from garud360.core.plc.registry import DRIVERS
from garud360.ui.context import AppContext
from garud360.ui.theme import C, STATUS_KIND
from garud360.ui.util import confirm, error_box, local_time
from garud360.ui.widgets.common import CameraTile, StatTile, StatusBadge
from garud360.ui.widgets.crane_widget import CraneWidget

FILTERS = ["All spaces", "Running", "Stopped", "Crane blocked", "Camera fault", "PLC fault", "Paused"]


def _plc_text(snap: SpaceSnapshot) -> tuple[str, str]:
    if not snap.running:
        return "Output: idle", "off"
    if snap.plc_connected:
        state = "BLOCKED" if snap.plc_confirmed_permit is False else "PERMITTED" if snap.plc_confirmed_permit else "..."
        return f"PLC linked - crane {state}", "ok" if snap.plc_confirmed_permit else "crit"
    return "PLC LINK DOWN - crane not interlocked", "crit"


def display_status(snap: SpaceSnapshot | None) -> tuple[str, str]:
    if snap is None or not snap.running:
        return "STOPPED", "off"
    if snap.stopping:
        return "STOPPING", "warn"
    return snap.status, STATUS_KIND.get(snap.status, "off")


class SpaceCard(QFrame):
    open_requested = Signal(int)

    def __init__(self, ctx: AppContext, space: Space, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx, self.space = ctx, space
        self.setObjectName("card")
        self.setMinimumWidth(300)
        self.setFixedHeight(200)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        top = QHBoxLayout()
        self.title = QLabel(space.name)
        self.title.setObjectName("h2")
        self.badge = StatusBadge("STOPPED")
        top.addWidget(self.title, 1)
        top.addWidget(self.badge)
        lay.addLayout(top)
        self.desc = QLabel(space.description or " ")
        self.desc.setProperty("muted", True)
        lay.addWidget(self.desc)
        self.cams = QLabel()
        self.plc = QLabel()
        self.viol = QLabel()
        for w in (self.cams, self.plc, self.viol):
            lay.addWidget(w)
        lay.addStretch(1)
        row = QHBoxLayout()
        self.toggle = QPushButton("Start")
        self.toggle.clicked.connect(self._toggle)
        self.open = QPushButton("Open live view")
        self.open.clicked.connect(lambda: self.open_requested.emit(self.space.id))
        row.addWidget(self.toggle)
        row.addWidget(self.open, 1)
        lay.addLayout(row)
        self.violations = 0
        self._sheet = ""
        self.refresh(None)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self.open_requested.emit(self.space.id)

    def _toggle(self) -> None:
        rt = self.ctx.runtime
        if rt.is_running(self.space.id):
            if confirm(self.window(), "Stop monitoring",
                       f"Stop '{self.space.name}'?\n\nThe zone will no longer be watched. Depending on the space "
                       "settings the crane output is blocked when monitoring stops.", True):
                rt.stop_space(self.space.id)
        else:
            try:
                rt.start_space(self.space.id)
            except SpaceStartError as exc:
                error_box(self.window(), "Cannot start", str(exc))

    def refresh(self, snap: SpaceSnapshot | None) -> None:
        text, key = display_status(snap)
        self.badge.set_status(text, key)
        n = len(self.space.cameras)
        running = bool(snap and snap.running)
        if running and snap:
            ok = sum(1 for c in snap.cameras if c.ok)
            self.cams.setText(f"Cameras: {ok}/{len(snap.cameras)} online  |  Persons in view: {snap.persons}")
            t, k = _plc_text(snap)
            self.plc.setText(t)
            self.plc.setStyleSheet(f"color: {C[k]};")
        else:
            self.cams.setText(f"Cameras: {n} configured")
            self.plc.setText(f"Output: {DRIVERS[self.space.plc_config.get('type', 'simulated')].LABEL}"
                             if self.space.plc_config.get("type") in DRIVERS else "Output: not set")
            self.plc.setStyleSheet(f"color: {C['muted']};")
        self.viol.setText(f"Violations today: {self.violations}")
        self.toggle.setText("Stop" if running else "Start")
        want = "danger" if running else "ok"
        if self.toggle.objectName() != want:
            self.toggle.setObjectName(want)
            self.toggle.setStyle(self.toggle.style())
        self.toggle.setEnabled(not (snap and snap.stopping))
        sheet = f"QFrame#card {{ border: 2px solid {C['crit']}; }}" if key == "crit" else ""
        if sheet != self._sheet:
            self._sheet = sheet
            self.setStyleSheet(sheet)


class SpaceView(QWidget):
    back = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.space: Space | None = None
        self.tiles: dict[int, CameraTile] = {}
        self._tick = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        b = QPushButton("← All spaces")
        b.clicked.connect(self.back.emit)
        self.title = QLabel("")
        self.title.setObjectName("h1")
        self.badge = StatusBadge("")
        head.addWidget(b)
        head.addWidget(self.title)
        head.addWidget(self.badge)
        head.addStretch(1)
        self.start_btn = QPushButton("Start monitoring")
        self.start_btn.clicked.connect(self._toggle)
        self.pause_min = QSpinBox()
        self.pause_min.setRange(1, 240)
        self.pause_min.setSuffix(" min")
        self.pause_btn = QPushButton("Pause AI")
        self.pause_btn.setToolTip("Pause detection and unblock the crane so a load can be attached or detached. "
                                  "Monitoring resumes automatically when the time is up.")
        self.pause_btn.clicked.connect(self._pause)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Acknowledge a latched violation (only accepted when the zone is clear).")
        self.reset_btn.clicked.connect(self._reset)
        for w in (self.pause_min, self.pause_btn, self.reset_btn, self.start_btn):
            head.addWidget(w)
        root.addLayout(head)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.grid_host, 3)
        side = QVBoxLayout()
        body.addLayout(side, 2)
        self.crane = CraneWidget()
        self.crane.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        side.addWidget(self.crane)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        side.addWidget(self.info)
        side.addWidget(QLabel("Recent events"))
        self.events = QListWidget()
        side.addWidget(self.events, 1)
        self._last_event = -1

    def show_space(self, space: Space) -> None:
        self.space = space
        self.title.setText(space.name)
        for t in self.tiles.values():
            t.setParent(None)
            t.deleteLater()
        self.tiles.clear()
        n = len(space.cameras)
        cols = 1 if n <= 1 else 2 if n <= 4 else 3 if n <= 9 else 4
        for i, cam in enumerate(space.cameras):
            tile = CameraTile(cam.id, cam.name)
            self.tiles[cam.id] = tile
            self.grid.addWidget(tile, i // cols, i % cols)
        if n == 0:
            self.grid.addWidget(QLabel("This space has no cameras yet."), 0, 0)
        self.pause_min.setValue(int(self.ctx.settings.effective(space.overrides)["pause_minutes"]))
        self._last_event = -1
        self.refresh(1)

    # -- actions
    def _toggle(self) -> None:
        if not self.space:
            return
        rt = self.ctx.runtime
        if rt.is_running(self.space.id):
            if confirm(self, "Stop monitoring", "Stop monitoring this space? The crane output follows the "
                                                "'Block crane when monitoring stops' setting.", True):
                rt.stop_space(self.space.id)
        else:
            try:
                rt.start_space(self.space.id)
            except SpaceStartError as exc:
                error_box(self, "Cannot start", str(exc))

    def _pause(self) -> None:
        mon = self.ctx.runtime.monitor(self.space.id) if self.space else None
        if not mon:
            return
        if mon.snapshot().status_enum == Status.PAUSED:
            mon.resume(self.ctx.username)
            return
        if confirm(self, "Pause AI", f"Pause detection for {self.pause_min.value()} minute(s)?\n\n"
                                      "While paused the crane is NOT blocked and nobody is watched.", True):
            mon.pause(self.pause_min.value(), self.ctx.username)

    def _reset(self) -> None:
        mon = self.ctx.runtime.monitor(self.space.id) if self.space else None
        if mon:
            if not mon.reset(self.ctx.username):
                QMessageBox.information(self, "Reset", "Reset not accepted: nothing is latched, or the zone is not clear yet.")

    # -- refresh
    def refresh(self, ticks: int = 1) -> None:
        if not self.space:
            return
        mon = self.ctx.runtime.monitor(self.space.id)
        snap = mon.snapshot() if mon and mon.running else None
        running = bool(snap)
        text, key = display_status(snap)
        self.badge.set_status(text, key)
        self.start_btn.setText("Stop monitoring" if running else "Start monitoring")
        want = "danger" if running else "ok"
        if self.start_btn.objectName() != want:
            self.start_btn.setObjectName(want)
            self.start_btn.setStyle(self.start_btn.style())
        paused = bool(snap and snap.status_enum == Status.PAUSED)
        self.pause_btn.setText("Resume now" if paused else "Pause AI")
        self.pause_btn.setEnabled(running)
        self.pause_min.setEnabled(running and not paused)
        self.reset_btn.setEnabled(bool(snap and snap.latched))
        crane_snap = mon.crane() if mon else None
        plc_label = DRIVERS[snap.plc_type].LABEL if snap and snap.plc_type in DRIVERS else ""
        self.crane.set_state(crane_snap, running, snap.permit if snap else None,
                             bool(snap and snap.status_enum == Status.PERSON), text, plc_label)
        # cameras (drawn at the preview rate only)
        pw = int(self.ctx.settings.all()["preview_max_width"])
        stat = {c.camera_id: c for c in snap.cameras} if snap else {}
        for cid, tile in self.tiles.items():
            if mon and mon.running:
                frame = mon.render_camera(cid, pw)
                tile.set_frame(frame)
                cs = stat.get(cid)
                tile.set_alert("crit" if cs and (cs.person_active or not cs.ok) else "ok")
            else:
                tile.set_frame(None, "Monitoring stopped")
                tile.set_alert("ok")
        if snap:
            t, k = _plc_text(snap)
            lines = [f"<b>Reason:</b> {snap.reason or '-'}", f"<b>Output:</b> <span style='color:{C[k]}'>{t}</span>"]
            if paused:
                lines.append(f"<b>Auto-resume in:</b> {int(snap.pause_remaining_s // 60)}:{int(snap.pause_remaining_s % 60):02d}")
            if snap.plc_error and not snap.plc_connected:
                lines.append(f"<span style='color:{C['crit']}'>{snap.plc_error}</span>")
            bad = [f"{c.name}: {c.detail}" for c in snap.cameras if not c.ok]
            if bad:
                lines.append(f"<span style='color:{C['crit']}'>Camera problems:<br>" + "<br>".join(bad) + "</span>")
            self.info.setText("<br>".join(lines))
        else:
            self.info.setText("<span style='color:%s'>Monitoring is stopped. Press Start monitoring.</span>" % C["muted"])

    def refresh_events(self) -> None:
        if not self.space:
            return
        last = self.ctx.events.last_id()
        if last == self._last_event:
            return
        self._last_event = last
        self.events.clear()
        for e in self.ctx.events.search(space_id=self.space.id, limit=40):
            self.events.addItem(f"{local_time(e.ts, '%H:%M:%S')}  {e.camera_name + ': ' if e.camera_name else ''}{e.message}")


class DashboardPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self.cards: dict[int, SpaceCard] = {}
        self._spaces_key: tuple = ()
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.addWidget(self.stack)

        # ---- overview
        ov = QWidget()
        lay = QVBoxLayout(ov)
        lay.setContentsMargins(0, 0, 0, 0)
        h = QLabel("Dashboard")
        h.setObjectName("h1")
        lay.addWidget(h)
        tiles = QHBoxLayout()
        self.t_spaces, self.t_running = StatTile("Spaces"), StatTile("Running")
        self.t_blocked, self.t_cam = StatTile("Crane blocked"), StatTile("Camera faults")
        self.t_plc, self.t_viol = StatTile("PLC link faults"), StatTile("Violations today")
        for t in (self.t_spaces, self.t_running, self.t_blocked, self.t_cam, self.t_plc, self.t_viol):
            tiles.addWidget(t)
        lay.addLayout(tiles)
        self.engine = QLabel()
        self.engine.setProperty("muted", True)
        self.engine.setWordWrap(True)
        lay.addWidget(self.engine)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search spaces ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._layout_cards)
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(self._layout_cards)
        self.start_all = QPushButton("Start all")
        self.start_all.clicked.connect(self._start_all)
        self.stop_all = QPushButton("Stop all")
        self.stop_all.clicked.connect(self._stop_all)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.filter)
        bar.addWidget(self.start_all)
        bar.addWidget(self.stop_all)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll, 1)
        self.empty = QLabel("No spaces yet. Open the 'Spaces' page to create your first space.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setProperty("muted", True)
        lay.addWidget(self.empty)
        self.stack.addWidget(ov)
        self.view = SpaceView(ctx)
        self.view.back.connect(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.view)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._last_overview = 0.0

    # lifecycle -----------------------------------------------------------------------------
    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._reload_spaces()
        self.timer.start(100)

    def hideEvent(self, e) -> None:  # noqa: N802
        super().hideEvent(e)
        self.timer.stop()

    def reload(self) -> None:
        self._reload_spaces(force=True)

    def _reload_spaces(self, force: bool = False) -> None:
        spaces = self.ctx.spaces.list()
        key = tuple((s.id, s.name, s.description, len(s.cameras), s.plc_config.get("type")) for s in spaces)
        if key == self._spaces_key and not force:
            return
        self._spaces_key = key
        for c in self.cards.values():
            c.setParent(None)
            c.deleteLater()
        self.cards.clear()
        for s in spaces:
            card = SpaceCard(self.ctx, s)
            card.open_requested.connect(self._open_space)
            self.cards[s.id] = card
        self._layout_cards()

    def _open_space(self, space_id: int) -> None:
        sp = self.ctx.spaces.get(space_id)
        self.view.show_space(sp)
        self.stack.setCurrentIndex(1)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._layout_cards()

    # filtering & layout ------------------------------------------------------------------
    def _matches(self, s: Space, snap: SpaceSnapshot | None) -> bool:
        q = self.search.text().strip().lower()
        if q and q not in s.name.lower() and q not in s.description.lower():
            return False
        f = self.filter.currentText()
        running = bool(snap and snap.running)
        if f == "Running":
            return running
        if f == "Stopped":
            return not running
        if f == "Crane blocked":
            return running and not snap.permit               # type: ignore[union-attr]
        if f == "Camera fault":
            return running and snap.camera_faults > 0        # type: ignore[union-attr]
        if f == "PLC fault":
            return running and not snap.plc_connected        # type: ignore[union-attr]
        if f == "Paused":
            return running and snap.status_enum == Status.PAUSED   # type: ignore[union-attr]
        return True

    def _layout_cards(self) -> None:
        snaps = self.ctx.runtime.snapshots()
        while self.grid.count():
            self.grid.takeAt(0)
        width = max(self.scroll.viewport().width(), 320)
        cols = max(1, width // 330)
        i = 0
        for sid, card in self.cards.items():
            show = self._matches(card.space, snaps.get(sid))
            card.setVisible(show)
            if show:
                self.grid.addWidget(card, i // cols, i % cols)
                i += 1
        self.empty.setVisible(not self.cards)
        self.empty.setText("No spaces yet. Open the 'Spaces' page to create your first space." if not self.cards
                           else "")
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    # bulk actions -------------------------------------------------------------------------------
    def _start_all(self) -> None:
        errs = self.ctx.runtime.start_all()
        if errs:
            error_box(self, "Some spaces did not start", "\n".join(errs))

    def _stop_all(self) -> None:
        if self.ctx.runtime.snapshots() and confirm(self, "Stop all", "Stop monitoring in ALL spaces?", True):
            self.ctx.runtime.stop_all()

    # periodic refresh -------------------------------------------------------------------------------
    def _tick(self) -> None:
        fps = max(1, int(self.ctx.settings.all()["preview_fps"]))
        now = time.monotonic()
        if self.stack.currentIndex() == 1:
            if now - getattr(self, "_last_view", 0.0) >= 1.0 / fps:
                self._last_view = now
                self.view.refresh()
            self.view.refresh_events()
        if now - self._last_overview >= 0.5:
            self._last_overview = now
            self._refresh_overview()

    def _refresh_overview(self) -> None:
        self._reload_spaces()
        snaps = self.ctx.runtime.snapshots()
        today = self.ctx.events.per_space_today()
        running = [s for s in snaps.values() if s.running]
        for sid, card in self.cards.items():
            card.violations = today.get(sid, 0)
            card.refresh(snaps.get(sid))
        self.t_spaces.set_value(len(self.cards))
        self.t_running.set_value(len(running), "ok" if running else None)
        blocked = sum(1 for s in running if not s.permit)
        self.t_blocked.set_value(blocked, "crit" if blocked else None)
        faults = sum(1 for s in running if s.camera_faults)
        self.t_cam.set_value(faults, "crit" if faults else None)
        plc = sum(1 for s in running if not s.plc_connected)
        self.t_plc.set_value(plc, "crit" if plc else None)
        v = sum(today.values())
        self.t_viol.set_value(v, "warn" if v else None)
        st = self.ctx.runtime.engine_status()
        if running or st.state in ("loading", "error"):
            col = {"ready": C["ok"], "loading": C["warn"], "error": C["crit"]}.get(st.state, C["muted"])
            cap = ""
            if st.ms_per_image > 0:
                cap_fps = 1000.0 / st.ms_per_image
                load = st.demand_fps / cap_fps * 100 if cap_fps else 0
                cap = (f" | {st.ms_per_image:.0f} ms/frame, capacity ~{cap_fps:.0f} fps, demand ~{st.demand_fps:.0f} fps "
                       f"({load:.0f}% load)")
                if load > 90:
                    cap += " - OVERLOADED: lower the detection speed, use a smaller model or add a GPU"
            self.engine.setText(f"<span style='color:{col}'>Detection engine: {st.state.upper()}</span> "
                                f"{st.model} {st.message}{cap}")
        else:
            self.engine.setText("Detection engine idle - starts when the first space is started.")
        self._layout_visibility_only(snaps)

    def _layout_visibility_only(self, snaps) -> None:
        # re-evaluate filters only when the visible set changes (avoids flicker while typing / refreshing)
        visible = tuple(sid for sid, c in self.cards.items() if self._matches(c.space, snaps.get(sid)))
        shown = tuple(sid for sid, c in self.cards.items() if not c.isHidden())
        if visible != shown:
            self._layout_cards()
