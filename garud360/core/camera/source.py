# garud360/core/camera/source.py
"""Camera source definitions: validation and the list of URLs/devices to try."""
from __future__ import annotations

import ipaddress
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from garud360.core.models import SRC_DROIDCAM, SRC_FILE, SRC_HTTP, SRC_RTSP, SRC_WEBCAM

_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")


@dataclass(frozen=True)
class OpenSpec:
    """One concrete way to open a capture: a URL / file path, or a local device index."""
    kind: str                # "url" | "index" | "file"
    target: str | int
    label: str


def _valid_host(host: str) -> bool:
    host = host.strip()
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOST_RE.match(host))


def _port(value: Any, default: int) -> int | None:
    if value in (None, ""):
        return default
    try:
        p = int(str(value).strip())
    except ValueError:
        return None
    return p if 1 <= p <= 65535 else None


def validate_source(source_type: str, cfg: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems (empty list = valid)."""
    errs: list[str] = []
    if source_type == SRC_DROIDCAM:
        if not _valid_host(str(cfg.get("ip", ""))):
            errs.append("Enter the phone's IP address (for example 192.168.1.25).")
        if _port(cfg.get("port"), 4747) is None:
            errs.append("Port must be a number between 1 and 65535 (DroidCam default is 4747).")
    elif source_type == SRC_WEBCAM:
        try:
            if int(cfg.get("index", 0)) < 0:
                raise ValueError
        except (TypeError, ValueError):
            errs.append("Camera index must be 0 or a positive number.")
    elif source_type in (SRC_RTSP, SRC_HTTP):
        url = str(cfg.get("url", "")).strip()
        allowed = ("rtsp", "rtsps") if source_type == SRC_RTSP else ("http", "https")
        parts = urlsplit(url)
        if parts.scheme.lower() not in allowed or not parts.hostname:
            errs.append(f"Enter a full URL starting with {' or '.join(a + '://' for a in allowed)}")
    elif source_type == SRC_FILE:
        p = str(cfg.get("path", "")).strip()
        if not p:
            errs.append("Choose a video file.")
    else:
        errs.append(f"Unknown camera type '{source_type}'.")
    return errs


def build_open_specs(source_type: str, cfg: dict[str, Any]) -> list[OpenSpec]:
    """Candidates to try, in order, when (re)connecting."""
    errs = validate_source(source_type, cfg)
    if errs:
        raise ValueError(errs[0])
    if source_type == SRC_DROIDCAM:
        ip = str(cfg["ip"]).strip()
        port = _port(cfg.get("port"), 4747)
        host = f"[{ip}]" if ":" in ip else ip
        return [OpenSpec("url", f"http://{host}:{port}/video", "DroidCam /video"),
                OpenSpec("url", f"http://{host}:{port}/mjpegfeed?640x480", "DroidCam /mjpegfeed")]
    if source_type == SRC_WEBCAM:
        return [OpenSpec("index", int(cfg.get("index", 0)), f"Camera #{int(cfg.get('index', 0))}")]
    if source_type in (SRC_RTSP, SRC_HTTP):
        return [OpenSpec("url", str(cfg["url"]).strip(), "Stream URL")]
    return [OpenSpec("file", str(cfg["path"]).strip(), Path(str(cfg["path"])).name)]


def mask_url(text: str) -> str:
    """Hide credentials inside a URL for logging/UI."""
    try:
        parts = urlsplit(text)
        if parts.username or parts.password:
            host = parts.hostname or ""
            if parts.port:
                host += f":{parts.port}"
            return urlunsplit((parts.scheme, f"***:***@{host}", parts.path, parts.query, parts.fragment))
    except ValueError:
        pass
    return text


def describe(source_type: str, cfg: dict[str, Any]) -> str:
    if source_type == SRC_DROIDCAM:
        return f"{cfg.get('ip', '?')}:{cfg.get('port', 4747)}"
    if source_type == SRC_WEBCAM:
        return f"Camera #{cfg.get('index', 0)}"
    if source_type in (SRC_RTSP, SRC_HTTP):
        return mask_url(str(cfg.get("url", "")))
    if source_type == SRC_FILE:
        return Path(str(cfg.get("path", ""))).name
    return ""


def is_windows() -> bool:
    return sys.platform == "win32"
