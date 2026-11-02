# garud360/core/models.py
"""Plain data models shared by the database, the runtime and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# camera source types
SRC_DROIDCAM = "droidcam"
SRC_WEBCAM = "webcam"
SRC_RTSP = "rtsp"
SRC_HTTP = "http_mjpeg"
SRC_FILE = "file"

SOURCE_LABELS = {
    SRC_DROIDCAM: "DroidCam (Android / iPhone)",
    SRC_WEBCAM: "Laptop / USB camera",
    SRC_RTSP: "IP camera (RTSP)",
    SRC_HTTP: "HTTP / MJPEG stream",
    SRC_FILE: "Video file (testing)",
}

# event kinds
EV_PERSON = "person_violation"
EV_CAM_FAULT = "camera_fault"
EV_CAM_OK = "camera_recovered"
EV_BLOCKED = "crane_blocked"
EV_RELEASED = "crane_released"
EV_PLC_FAULT = "plc_fault"
EV_PLC_OK = "plc_recovered"
EV_STARTED = "space_started"
EV_STOPPED = "space_stopped"
EV_PAUSED = "paused"
EV_RESUMED = "resumed"
EV_RESET = "reset"
EV_ENGINE = "engine_fault"

SEV_INFO = "info"
SEV_WARN = "warning"
SEV_CRIT = "critical"


@dataclass
class User:
    id: int
    username: str
    role: str
    must_change_password: bool = False
    active: bool = True
    created_at: str = ""
    last_login_at: str | None = None


@dataclass
class Camera:
    id: int
    space_id: int
    name: str
    source_type: str
    source_config: dict[str, Any] = field(default_factory=dict)
    roi: list[tuple[float, float]] | None = None   # normalised polygon, 0..1
    enabled: bool = True
    position: int = 0


@dataclass
class Space:
    id: int
    name: str
    description: str = ""
    plc_config: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)
    auto_start: bool = False
    created_at: str = ""
    updated_at: str = ""
    cameras: list[Camera] = field(default_factory=list)


@dataclass
class Event:
    id: int
    ts: str
    day: str
    space_id: int | None
    space_name: str
    camera_id: int | None
    camera_name: str
    kind: str
    severity: str
    message: str
    snapshot_path: str | None
