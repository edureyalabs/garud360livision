# garud360/config/settings_schema.py
"""Single source of truth for every tunable setting.

The schema drives: validation, the Settings console, the per-space override form,
and the generated settings guide (docs/SETTINGS_GUIDE.md and the in-app guide).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

G_MODEL = "Model & Hardware"
G_DETECT = "Detection"
G_ROI = "Region of Interest"
G_CAMERA = "Cameras"
G_INTERLOCK = "Crane Interlock"
G_PLC = "PLC Link"
G_ALERT = "Alerts & Siren"
G_SNAP = "Snapshots & Retention"
G_UI = "Display"

GROUP_ORDER = [G_MODEL, G_DETECT, G_ROI, G_CAMERA, G_INTERLOCK, G_PLC, G_ALERT, G_SNAP, G_UI]


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    group: str
    kind: str                      # int | float | bool | choice | str
    default: Any
    help: str
    increase: str = ""
    decrease: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""
    choices: tuple[str, ...] = ()
    editable_choice: bool = False  # choice combo that also accepts free text
    per_space: bool = False        # may be overridden inside a space


S = SettingDef

SETTINGS: tuple[SettingDef, ...] = (
    # ------------------------------------------------------------------ MODEL
    S("model_task", "Model type", G_MODEL, "choice", "segment",
      "'segment' draws a pixel-accurate outline around each person. 'detect' draws only boxes. "
      "The person / no-person decision is made the same way either way.",
      increase="segment: draws outlines (clearer view, best for review), somewhat slower and heavier than detect.",
      decrease="detect: boxes only - faster and lighter, a good choice when many cameras share one machine.",
      choices=("segment", "detect")),
    S("model_size", "Model size", G_MODEL, "choice", "n",
      "Model size: n (nano) < s < m < l < x (extra large). Bigger = more accurate but slower and heavier.",
      increase="Moving n -> x: fewer missed/false people, but each frame takes several times longer, so you can "
               "serve fewer cameras.",
      decrease="Moving x -> n: much faster and lighter (best for laptops/CPU), but small or distant people are "
               "missed more often.",
      choices=("n", "s", "m", "l", "x")),
    S("custom_model_path", "Custom model path (optional)", G_MODEL, "str", "",
      "Full path to your own weights or an exported model (.pt, .onnx, .engine, or an OpenVINO "
      "'..._openvino_model' folder). When set it OVERRIDES model type and size.",
      increase="Set: your own / exported model is used (make sure 'Image size' matches its export size).",
      decrease="Empty: the standard built-in model is used (downloaded automatically on first run)."),
    S("inference_device", "Inference device", G_MODEL, "choice", "auto",
      "Where the model runs. 'auto' lets Ultralytics choose (GPU if available). Use cuda:0 for an NVIDIA GPU, "
      "cpu to force CPU, intel:gpu / intel:cpu for OpenVINO-exported models.",
      increase="cuda:0 / cuda:1: uses the NVIDIA GPU - several times faster, needs a CUDA build of PyTorch.",
      decrease="cpu: works everywhere but is the slowest; use a smaller model size and a lower detection speed.",
      choices=("auto", "cpu", "cuda:0", "cuda:1", "intel:gpu", "intel:cpu"), editable_choice=True),
    S("image_size", "Image size", G_MODEL, "int", 640,
      "Resolution (pixels, multiple of 32) the frame is resized to before detection. Exported models "
      "(OpenVINO/ONNX/TensorRT) must use the size they were exported with.",
      increase="Larger (800, 960...): finds smaller/farther people, but is slower and uses more memory.",
      decrease="Smaller (480, 320...): faster, but distant people are missed more often.",
      minimum=160, maximum=1920, step=32, unit="px"),
    S("half_precision", "Half precision (FP16)", G_MODEL, "bool", False,
      "Runs the model in 16-bit floats. Only works on NVIDIA GPUs.",
      increase="ON: noticeably faster on supported GPUs, negligible accuracy change.",
      decrease="OFF: safest default; required on CPU."),
    S("max_batch_size", "Max frames per batch", G_MODEL, "int", 4,
      "How many camera frames are sent to the model together. The scheduler always serves the camera "
      "that has waited longest, so every camera gets a fair turn.",
      increase="Higher: better GPU throughput with many cameras, slightly higher latency per frame.",
      decrease="1: lowest latency per frame; best on CPU-only machines.",
      minimum=1, maximum=16, step=1),

    # --------------------------------------------------------------- DETECTION
    S("person_conf", "Person confidence threshold", G_DETECT, "float", 0.40,
      "Minimum model confidence for a detection to count as a person. A detection exactly at the value counts.",
      increase="Higher (0.6, 0.7): fewer false alarms, but real people that are partly hidden or far away may be missed. "
               "Be careful: a missed person is a safety risk.",
      decrease="Lower (0.25, 0.30): catches more people (safer), but shadows, posts or machinery trigger more false blocks.",
      minimum=0.05, maximum=0.95, step=0.01, per_space=True),
    S("min_persons", "Persons needed to trigger", G_DETECT, "int", 1,
      "Number of persons (after the threshold and region filter) visible at the same time before a frame counts as a hit.",
      increase="Higher: the crane is blocked only when a group is present. Not recommended for safety zones.",
      decrease="1 (default): a single person blocks the crane - the safest setting.",
      minimum=1, maximum=50, step=1, per_space=True),
    S("trigger_frames", "Trigger frames", G_DETECT, "int", 3,
      "Consecutive analysed frames with a hit required before the crane is blocked. Time = frames / detection speed "
      "(default 3 frames at 8 fps is about 0.4 s).",
      increase="Higher: ignores one-frame glitches (fewer false blocks) but reacts later to a real person.",
      decrease="1: reacts instantly, but a single noisy frame can block the crane.",
      minimum=1, maximum=100, step=1, unit="frames", per_space=True),
    S("release_frames", "Release frames", G_DETECT, "int", 15,
      "Consecutive analysed frames with NO hit required before the crane is released. Time = frames / detection speed "
      "(default 15 frames at 8 fps is about 1.9 s).",
      increase="Higher: the crane stays blocked longer after the person leaves and survives brief detection dropouts "
               "(safer, slower to resume).",
      decrease="Lower: the crane resumes sooner, but a person briefly hidden behind a post could release the crane early.",
      minimum=1, maximum=600, step=1, unit="frames", per_space=True),
    S("inference_fps", "Detection speed per camera", G_DETECT, "float", 8.0,
      "Maximum analysed frames per second for EACH camera. Frames in between are skipped so the machine is not overloaded.",
      increase="Higher: faster reaction and smoother overlays, but total load on the CPU/GPU grows with every camera.",
      decrease="Lower: allows more cameras on a weak machine, but trigger/release times (measured in frames) get longer.",
      minimum=0.5, maximum=30.0, step=0.5, unit="fps", per_space=True),
    S("draw_masks", "Draw person outlines (segment model)", G_DETECT, "bool", True,
      "Shows the pixel mask of each person on the live view (segment model only). Has no effect on safety logic.",
      increase="ON: clearer view, slightly more CPU for drawing.",
      decrease="OFF: boxes only, a little lighter on the UI.", per_space=True),
    S("detection_stale_s", "Detection watchdog", G_DETECT, "float", 5.0,
      "If a camera produces no new detection result for this long (model overloaded, crashed or still loading) it is "
      "treated as a camera fault and blocks the crane. This protects against 'blind' monitoring.",
      increase="Higher: tolerates slow machines / long model loads before blocking, but blind time is longer.",
      decrease="Lower: reacts faster to a stalled detector, but a busy machine may cause false camera-fault blocks.",
      minimum=1.0, maximum=60.0, step=0.5, unit="s", per_space=True),

    # -------------------------------------------------------------------- ROI
    S("roi_enabled", "Use camera regions of interest", G_ROI, "bool", True,
      "When ON, only persons inside the region (polygon) drawn for a camera count. Cameras with no region drawn "
      "watch the whole picture.",
      increase="ON: ignores people walking in safe areas of the picture (fewer false blocks).",
      decrease="OFF: every person anywhere in the picture counts.", per_space=True),
    S("roi_match_mode", "Region match rule", G_ROI, "choice", "any_overlap",
      "How a person is matched to the region. any_overlap: any part of the person box touches the region (most "
      "cautious). box_center: the centre of the box is inside. foot_point: the bottom-middle of the box (the feet) "
      "is inside - best for floor zones.",
      increase="any_overlap: blocks as soon as a person touches the zone (most cautious, most false alarms).",
      decrease="foot_point: blocks only when the feet are inside the zone - use it if tall people standing just outside "
               "trigger false blocks.",
      choices=("any_overlap", "box_center", "foot_point"), per_space=True),

    # ---------------------------------------------------------------- CAMERAS
    S("connect_timeout_s", "Camera connect timeout", G_CAMERA, "float", 8.0,
      "How long to wait for a camera to open before the attempt is abandoned and retried.",
      increase="Higher: copes with slow Wi-Fi / phones, but a dead camera is reported later.",
      decrease="Lower: dead cameras are detected sooner, but slow cameras may never connect.",
      minimum=2.0, maximum=60.0, step=0.5, unit="s"),
    S("stale_frame_s", "Stream-lost timeout", G_CAMERA, "float", 5.0,
      "A connected camera that delivers no new frame for this long is treated as lost (camera fault) and reconnected.",
      increase="Higher: tolerates brief Wi-Fi hiccups, but a frozen camera stays unnoticed longer.",
      decrease="Lower: faster fault alert, but short network stalls cause false camera-fault blocks.",
      minimum=1.0, maximum=60.0, step=0.5, unit="s"),
    S("reconnect_initial_s", "Reconnect delay (first retry)", G_CAMERA, "float", 2.0,
      "Wait before the first reconnect attempt. The delay doubles after each failure up to the maximum below.",
      increase="Higher: gentler on the network/camera.", decrease="Lower: recovers sooner after a glitch.",
      minimum=0.5, maximum=30.0, step=0.5, unit="s"),
    S("reconnect_max_s", "Reconnect delay (maximum)", G_CAMERA, "float", 30.0,
      "Upper limit of the reconnect back-off.",
      increase="Higher: fewer connection attempts to a long-dead camera.",
      decrease="Lower: a returning camera is noticed sooner.",
      minimum=2.0, maximum=300.0, step=1.0, unit="s"),
    S("camera_fault_blocks_crane", "Camera fault blocks crane", G_CAMERA, "bool", True,
      "A disconnected, frozen or stalled camera is handled like a detected person: the crane is blocked until it recovers.",
      increase="ON (default): the crane never runs with a blind spot. Recommended.",
      decrease="OFF: camera faults only raise an alert; the crane keeps running unmonitored.", per_space=True),

    # -------------------------------------------------------------- INTERLOCK
    S("latch_until_reset", "Stay blocked until manual reset", G_INTERLOCK, "bool", False,
      "OFF: the crane is released automatically when the zone is clear. ON: after a violation the crane stays blocked "
      "(and the siren keeps sounding) until an operator presses Reset in the app or the reset input of the crane remote "
      "is pulsed - even if the person has left.",
      increase="ON: strictest; an operator must acknowledge every violation.",
      decrease="OFF: crane resumes by itself once the release frames have passed.", per_space=True),
    S("pause_minutes", "Default pause length", G_INTERLOCK, "int", 5,
      "Pausing suspends detection AND blocking so the crew can attach or detach a load. Monitoring resumes "
      "automatically after this many minutes.",
      increase="Longer pauses give crews more time but leave the zone unmonitored for longer.",
      decrease="Shorter pauses restore protection sooner but may expire before the job is finished (pause again).",
      minimum=1, maximum=240, step=1, unit="min", per_space=True),
    S("max_pause_minutes", "Maximum pause length", G_INTERLOCK, "int", 30,
      "Hard upper limit for any pause request, including those typed by an operator.",
      increase="Allows long maintenance pauses.", decrease="Prevents the zone being left unmonitored for long periods.",
      minimum=1, maximum=480, step=1, unit="min", per_space=True),
    S("block_on_stop", "Block crane when monitoring stops", G_INTERLOCK, "bool", True,
      "What the crane output does when a space is stopped (or the app is closed).",
      increase="ON (fail-safe): stopping monitoring also blocks the crane, because nobody is watching the zone.",
      decrease="OFF: the crane is released when monitoring stops (use only if another safety layer exists).",
      per_space=True),

    # -------------------------------------------------------------------- PLC
    S("plc_heartbeat_s", "PLC heartbeat / refresh interval", G_PLC, "float", 1.0,
      "The crane output is re-sent and the heartbeat bit toggles at this interval. Build a watchdog in the PLC that "
      "blocks the crane if the heartbeat stops (app crash, PC off, cable pulled).",
      increase="Higher: less network traffic, but the PLC needs a longer watchdog time, so loss is detected later.",
      decrease="Lower: PLC notices a dead app sooner; more traffic.",
      minimum=0.2, maximum=10.0, step=0.1, unit="s", per_space=True),
    S("plc_input_poll_s", "PLC input poll interval", G_PLC, "float", 0.25,
      "How often the optional PLC inputs (load present, reset, pause) are read.",
      increase="Higher: less traffic; reset/pause buttons feel slower.",
      decrease="Lower: snappier remote reset/pause; more traffic.",
      minimum=0.05, maximum=5.0, step=0.05, unit="s", per_space=True),
    S("plc_verify_writes", "Read back every write", G_PLC, "bool", True,
      "After writing the crane output, read it back and raise a PLC fault if it does not match.",
      increase="ON: detects a PLC that silently ignores or overwrites the bit. Recommended.",
      decrease="OFF: one fewer network round-trip per write.", per_space=True),
    S("plc_timeout_s", "PLC communication timeout", G_PLC, "float", 3.0,
      "Time to wait for the PLC to answer before the link is declared faulty.",
      increase="Higher: tolerates slow networks but a dead PLC is noticed later.",
      decrease="Lower: faster fault detection, more false faults on slow networks.",
      minimum=0.5, maximum=30.0, step=0.5, unit="s", per_space=True),
    S("plc_reconnect_s", "PLC reconnect interval", G_PLC, "float", 3.0,
      "Wait between reconnect attempts after the PLC link drops.",
      increase="Higher: less network noise.", decrease="Lower: link restored sooner.",
      minimum=0.5, maximum=60.0, step=0.5, unit="s", per_space=True),

    # ----------------------------------------------------------------- ALERTS
    S("siren_enabled", "Siren enabled", G_ALERT, "bool", True,
      "Sound the siren on this PC while a space is in violation (person, camera fault, latched).",
      increase="ON: audible alarm.", decrease="OFF: silent (on-screen alerts only).", per_space=True),
    S("siren_on_plc_fault", "Siren on PLC link fault", G_ALERT, "bool", True,
      "Also sound the siren when the PLC link of a running space is down, because the crane can then NOT be interlocked.",
      increase="ON: you cannot miss a broken interlock.", decrease="OFF: PLC faults are shown on screen only."),
    S("siren_low_hz", "Siren low tone", G_ALERT, "int", 900,
      "Lower pitch of the two-tone siren.", increase="Higher pitch.", decrease="Lower pitch.",
      minimum=200, maximum=4000, step=50, unit="Hz"),
    S("siren_high_hz", "Siren high tone", G_ALERT, "int", 1400,
      "Higher pitch of the two-tone siren.", increase="Higher pitch.", decrease="Lower pitch.",
      minimum=200, maximum=4000, step=50, unit="Hz"),
    S("siren_tone_ms", "Siren tone length", G_ALERT, "int", 300,
      "Length of each tone before it switches pitch.",
      increase="Slower warble.", decrease="Faster, more urgent warble.",
      minimum=100, maximum=2000, step=50, unit="ms"),

    # -------------------------------------------------------------- SNAPSHOTS
    S("snapshot_on_violation", "Save snapshot on violation", G_SNAP, "bool", True,
      "Save a picture of the annotated frame when a person violation starts. Shown in Events and the daily summary.",
      increase="ON: evidence for every violation.", decrease="OFF: saves disk space; no pictures in Events."),
    S("snapshot_quality", "Snapshot JPEG quality", G_SNAP, "int", 85,
      "JPEG quality of saved snapshots.",
      increase="Higher: sharper pictures, bigger files.", decrease="Lower: smaller files, more compression artefacts.",
      minimum=30, maximum=100, step=1, unit="%"),
    S("snapshot_cooldown_s", "Snapshot cool-down per camera", G_SNAP, "int", 10,
      "Minimum time between two snapshots of the same camera.",
      increase="Higher: fewer files during repeated violations.", decrease="Lower: more pictures; 0 = every violation.",
      minimum=0, maximum=300, step=1, unit="s"),
    S("snapshot_retention_days", "Keep snapshots for", G_SNAP, "int", 30,
      "Snapshot files older than this are deleted automatically at start-up and once a day.",
      increase="Longer history, more disk space.", decrease="Less disk space, shorter evidence history.",
      minimum=1, maximum=3650, step=1, unit="days"),
    S("event_retention_days", "Keep event log for", G_SNAP, "int", 180,
      "Event log rows older than this are deleted automatically.",
      increase="Longer audit trail.", decrease="Smaller database.",
      minimum=1, maximum=3650, step=1, unit="days"),

    # ---------------------------------------------------------------- DISPLAY
    S("preview_fps", "Live view refresh rate", G_UI, "int", 10,
      "How often the live camera tiles are redrawn. Does NOT change detection.",
      increase="Smoother video, more UI CPU.", decrease="Lighter UI, choppier video.",
      minimum=1, maximum=30, step=1, unit="fps"),
    S("preview_max_width", "Live view width", G_UI, "int", 640,
      "Pictures are shrunk to at most this width before drawing in the live tiles.",
      increase="Sharper tiles, more UI CPU.", decrease="Lighter UI, softer tiles.",
      minimum=160, maximum=1920, step=40, unit="px"),
)

BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}
PER_SPACE_KEYS: tuple[str, ...] = tuple(s.key for s in SETTINGS if s.per_space)
MODEL_KEYS: tuple[str, ...] = ("model_task", "model_size", "custom_model_path", "inference_device",
                               "image_size", "half_precision")


def defaults() -> dict[str, Any]:
    return {s.key: s.default for s in SETTINGS}


def coerce(key: str, value: Any) -> Any:
    """Validate and normalise one value. Raises ValueError with a readable message."""
    d = BY_KEY.get(key)
    if d is None:
        raise ValueError(f"Unknown setting: {key}")
    try:
        if d.kind == "bool":
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("1", "true", "yes", "on"):
                    return True
                if v in ("0", "false", "no", "off"):
                    return False
                raise ValueError
            return bool(value)
        if d.kind == "int":
            if isinstance(value, bool):
                raise ValueError
            iv = int(round(float(value)))
            return _clamp_check(d, iv)
        if d.kind == "float":
            if isinstance(value, bool):
                raise ValueError
            fv = float(value)
            if fv != fv or fv in (float("inf"), float("-inf")):
                raise ValueError
            return _clamp_check(d, fv)
        if d.kind == "choice":
            sv = str(value).strip()
            if d.editable_choice and sv:
                return sv
            if sv not in d.choices:
                raise ValueError(f"must be one of {', '.join(d.choices)}")
            return sv
        return str(value).strip()
    except (TypeError, ValueError) as exc:
        extra = f" ({exc})" if str(exc) else ""
        raise ValueError(f"Invalid value for '{d.label}': {value!r}{extra}") from None


def _clamp_check(d: SettingDef, v: float | int) -> float | int:
    if d.minimum is not None and v < d.minimum:
        raise ValueError(f"minimum is {d.minimum:g}")
    if d.maximum is not None and v > d.maximum:
        raise ValueError(f"maximum is {d.maximum:g}")
    return v


def guide_markdown() -> str:
    """Render the full settings guide (also written to docs/SETTINGS_GUIDE.md)."""
    out = ["<!-- docs/SETTINGS_GUIDE.md (generated from garud360/config/settings_schema.py - do not edit by hand) -->",
           "# Garud 360 Li-Vision - Settings Guide", "",
           "Every value below can be changed in **Settings** (global defaults). Settings marked "
           "**per space** can also be overridden inside a space (Spaces > Edit > Detection & Behaviour).", ""]
    for group in GROUP_ORDER:
        items = [s for s in SETTINGS if s.group == group]
        if not items:
            continue
        out += [f"## {group}", ""]
        for s in items:
            rng = ""
            if s.minimum is not None or s.maximum is not None:
                rng = f" Range {s.minimum:g} - {s.maximum:g}{(' ' + s.unit) if s.unit else ''}."
            elif s.choices:
                rng = f" Options: {', '.join(s.choices)}."
            dv = f"{s.default}" if s.kind != "bool" else ("ON" if s.default else "OFF")
            unit = f" {s.unit}" if s.unit and s.kind != "bool" else ""
            out.append(f"### {s.label}{'  _(per space)_' if s.per_space else ''}")
            out.append(f"- **Default:** `{dv if dv != '' else '(empty)'}`{unit}.{rng}")
            out.append(f"- **What it does:** {s.help}")
            if s.increase:
                out.append(f"- **If you raise / turn it on:** {s.increase}")
            if s.decrease:
                out.append(f"- **If you lower / turn it off:** {s.decrease}")
            out.append("")
    return "\n".join(out)
