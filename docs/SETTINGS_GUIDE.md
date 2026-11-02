<!-- docs/SETTINGS_GUIDE.md (generated from garud360/config/settings_schema.py - do not edit by hand) -->
# Garud 360 Li-Vision - Settings Guide

Every value below can be changed in **Settings** (global defaults). Settings marked **per space** can also be overridden inside a space (Spaces > Edit > Detection & Behaviour).

## Model & Hardware

### Model type
- **Default:** `segment`. Options: segment, detect.
- **What it does:** 'segment' draws a pixel-accurate outline around each person (yolo26?-seg). 'detect' draws only boxes (yolo26?). The person / no-person decision is made the same way either way.
- **If you raise / turn it on:** segment: draws outlines (clearer view, best for review), somewhat slower and heavier than detect.
- **If you lower / turn it off:** detect: boxes only - faster and lighter, a good choice when many cameras share one machine.

### Model size
- **Default:** `n`. Options: n, s, m, l, x.
- **What it does:** YOLO26 size: n (nano) < s < m < l < x (extra large). Bigger = more accurate but slower and heavier.
- **If you raise / turn it on:** Moving n -> x: fewer missed/false people, but each frame takes several times longer, so you can serve fewer cameras.
- **If you lower / turn it off:** Moving x -> n: much faster and lighter (best for laptops/CPU), but small or distant people are missed more often.

### Custom model path (optional)
- **Default:** `(empty)`.
- **What it does:** Full path to your own weights or an exported model (.pt, .onnx, .engine, or an OpenVINO '..._openvino_model' folder). When set it OVERRIDES model type and size.
- **If you raise / turn it on:** Set: your own / exported model is used (make sure 'Image size' matches its export size).
- **If you lower / turn it off:** Empty: the standard YOLO26 weights are used (downloaded automatically on first run).

### Inference device
- **Default:** `auto`. Options: auto, cpu, cuda:0, cuda:1, intel:gpu, intel:cpu.
- **What it does:** Where the model runs. 'auto' lets Ultralytics choose (GPU if available). Use cuda:0 for an NVIDIA GPU, cpu to force CPU, intel:gpu / intel:cpu for OpenVINO-exported models.
- **If you raise / turn it on:** cuda:0 / cuda:1: uses the NVIDIA GPU - several times faster, needs a CUDA build of PyTorch.
- **If you lower / turn it off:** cpu: works everywhere but is the slowest; use a smaller model size and a lower detection speed.

### Image size
- **Default:** `640` px. Range 160 - 1920 px.
- **What it does:** Resolution (pixels, multiple of 32) the frame is resized to before detection. Exported models (OpenVINO/ONNX/TensorRT) must use the size they were exported with.
- **If you raise / turn it on:** Larger (800, 960...): finds smaller/farther people, but is slower and uses more memory.
- **If you lower / turn it off:** Smaller (480, 320...): faster, but distant people are missed more often.

### Half precision (FP16)
- **Default:** `OFF`.
- **What it does:** Runs the model in 16-bit floats. Only works on NVIDIA GPUs.
- **If you raise / turn it on:** ON: noticeably faster on supported GPUs, negligible accuracy change.
- **If you lower / turn it off:** OFF: safest default; required on CPU.

### Max frames per batch
- **Default:** `4`. Range 1 - 16.
- **What it does:** How many camera frames are sent to the model together. The scheduler always serves the camera that has waited longest, so every camera gets a fair turn.
- **If you raise / turn it on:** Higher: better GPU throughput with many cameras, slightly higher latency per frame.
- **If you lower / turn it off:** 1: lowest latency per frame; best on CPU-only machines.

## Detection

### Person confidence threshold  _(per space)_
- **Default:** `0.4`. Range 0.05 - 0.95.
- **What it does:** Minimum model confidence for a detection to count as a person. A detection exactly at the value counts.
- **If you raise / turn it on:** Higher (0.6, 0.7): fewer false alarms, but real people that are partly hidden or far away may be missed. Be careful: a missed person is a safety risk.
- **If you lower / turn it off:** Lower (0.25, 0.30): catches more people (safer), but shadows, posts or machinery trigger more false blocks.

### Persons needed to trigger  _(per space)_
- **Default:** `1`. Range 1 - 50.
- **What it does:** Number of persons (after the threshold and region filter) visible at the same time before a frame counts as a hit.
- **If you raise / turn it on:** Higher: the crane is blocked only when a group is present. Not recommended for safety zones.
- **If you lower / turn it off:** 1 (default): a single person blocks the crane - the safest setting.

### Trigger frames  _(per space)_
- **Default:** `3` frames. Range 1 - 100 frames.
- **What it does:** Consecutive analysed frames with a hit required before the crane is blocked. Time = frames / detection speed (default 3 frames at 8 fps is about 0.4 s).
- **If you raise / turn it on:** Higher: ignores one-frame glitches (fewer false blocks) but reacts later to a real person.
- **If you lower / turn it off:** 1: reacts instantly, but a single noisy frame can block the crane.

### Release frames  _(per space)_
- **Default:** `15` frames. Range 1 - 600 frames.
- **What it does:** Consecutive analysed frames with NO hit required before the crane is released. Time = frames / detection speed (default 15 frames at 8 fps is about 1.9 s).
- **If you raise / turn it on:** Higher: the crane stays blocked longer after the person leaves and survives brief detection dropouts (safer, slower to resume).
- **If you lower / turn it off:** Lower: the crane resumes sooner, but a person briefly hidden behind a post could release the crane early.

### Detection speed per camera  _(per space)_
- **Default:** `8.0` fps. Range 0.5 - 30 fps.
- **What it does:** Maximum analysed frames per second for EACH camera. Frames in between are skipped so the machine is not overloaded.
- **If you raise / turn it on:** Higher: faster reaction and smoother overlays, but total load on the CPU/GPU grows with every camera.
- **If you lower / turn it off:** Lower: allows more cameras on a weak machine, but trigger/release times (measured in frames) get longer.

### Draw person outlines (segment model)  _(per space)_
- **Default:** `ON`.
- **What it does:** Shows the pixel mask of each person on the live view (segment model only). Has no effect on safety logic.
- **If you raise / turn it on:** ON: clearer view, slightly more CPU for drawing.
- **If you lower / turn it off:** OFF: boxes only, a little lighter on the UI.

### Detection watchdog  _(per space)_
- **Default:** `5.0` s. Range 1 - 60 s.
- **What it does:** If a camera produces no new detection result for this long (model overloaded, crashed or still loading) it is treated as a camera fault and blocks the crane. This protects against 'blind' monitoring.
- **If you raise / turn it on:** Higher: tolerates slow machines / long model loads before blocking, but blind time is longer.
- **If you lower / turn it off:** Lower: reacts faster to a stalled detector, but a busy machine may cause false camera-fault blocks.

## Region of Interest

### Use camera regions of interest  _(per space)_
- **Default:** `ON`.
- **What it does:** When ON, only persons inside the region (polygon) drawn for a camera count. Cameras with no region drawn watch the whole picture.
- **If you raise / turn it on:** ON: ignores people walking in safe areas of the picture (fewer false blocks).
- **If you lower / turn it off:** OFF: every person anywhere in the picture counts.

### Region match rule  _(per space)_
- **Default:** `any_overlap`. Options: any_overlap, box_center, foot_point.
- **What it does:** How a person is matched to the region. any_overlap: any part of the person box touches the region (most cautious). box_center: the centre of the box is inside. foot_point: the bottom-middle of the box (the feet) is inside - best for floor zones.
- **If you raise / turn it on:** any_overlap: blocks as soon as a person touches the zone (most cautious, most false alarms).
- **If you lower / turn it off:** foot_point: blocks only when the feet are inside the zone - use it if tall people standing just outside trigger false blocks.

## Cameras

### Camera connect timeout
- **Default:** `8.0` s. Range 2 - 60 s.
- **What it does:** How long to wait for a camera to open before the attempt is abandoned and retried.
- **If you raise / turn it on:** Higher: copes with slow Wi-Fi / phones, but a dead camera is reported later.
- **If you lower / turn it off:** Lower: dead cameras are detected sooner, but slow cameras may never connect.

### Stream-lost timeout
- **Default:** `5.0` s. Range 1 - 60 s.
- **What it does:** A connected camera that delivers no new frame for this long is treated as lost (camera fault) and reconnected.
- **If you raise / turn it on:** Higher: tolerates brief Wi-Fi hiccups, but a frozen camera stays unnoticed longer.
- **If you lower / turn it off:** Lower: faster fault alert, but short network stalls cause false camera-fault blocks.

### Reconnect delay (first retry)
- **Default:** `2.0` s. Range 0.5 - 30 s.
- **What it does:** Wait before the first reconnect attempt. The delay doubles after each failure up to the maximum below.
- **If you raise / turn it on:** Higher: gentler on the network/camera.
- **If you lower / turn it off:** Lower: recovers sooner after a glitch.

### Reconnect delay (maximum)
- **Default:** `30.0` s. Range 2 - 300 s.
- **What it does:** Upper limit of the reconnect back-off.
- **If you raise / turn it on:** Higher: fewer connection attempts to a long-dead camera.
- **If you lower / turn it off:** Lower: a returning camera is noticed sooner.

### Camera fault blocks crane  _(per space)_
- **Default:** `ON`.
- **What it does:** A disconnected, frozen or stalled camera is handled like a detected person: the crane is blocked until it recovers.
- **If you raise / turn it on:** ON (default): the crane never runs with a blind spot. Recommended.
- **If you lower / turn it off:** OFF: camera faults only raise an alert; the crane keeps running unmonitored.

## Crane Interlock

### Stay blocked until manual reset  _(per space)_
- **Default:** `OFF`.
- **What it does:** OFF: the crane is released automatically when the zone is clear. ON: after a violation the crane stays blocked (and the siren keeps sounding) until an operator presses Reset in the app or the reset input of the crane remote is pulsed - even if the person has left.
- **If you raise / turn it on:** ON: strictest; an operator must acknowledge every violation.
- **If you lower / turn it off:** OFF: crane resumes by itself once the release frames have passed.

### Default pause length  _(per space)_
- **Default:** `5` min. Range 1 - 240 min.
- **What it does:** Pausing suspends detection AND blocking so the crew can attach or detach a load. Monitoring resumes automatically after this many minutes.
- **If you raise / turn it on:** Longer pauses give crews more time but leave the zone unmonitored for longer.
- **If you lower / turn it off:** Shorter pauses restore protection sooner but may expire before the job is finished (pause again).

### Maximum pause length  _(per space)_
- **Default:** `30` min. Range 1 - 480 min.
- **What it does:** Hard upper limit for any pause request, including those typed by an operator.
- **If you raise / turn it on:** Allows long maintenance pauses.
- **If you lower / turn it off:** Prevents the zone being left unmonitored for long periods.

### Block crane when monitoring stops  _(per space)_
- **Default:** `ON`.
- **What it does:** What the crane output does when a space is stopped (or the app is closed).
- **If you raise / turn it on:** ON (fail-safe): stopping monitoring also blocks the crane, because nobody is watching the zone.
- **If you lower / turn it off:** OFF: the crane is released when monitoring stops (use only if another safety layer exists).

## PLC Link

### PLC heartbeat / refresh interval  _(per space)_
- **Default:** `1.0` s. Range 0.2 - 10 s.
- **What it does:** The crane output is re-sent and the heartbeat bit toggles at this interval. Build a watchdog in the PLC that blocks the crane if the heartbeat stops (app crash, PC off, cable pulled).
- **If you raise / turn it on:** Higher: less network traffic, but the PLC needs a longer watchdog time, so loss is detected later.
- **If you lower / turn it off:** Lower: PLC notices a dead app sooner; more traffic.

### PLC input poll interval  _(per space)_
- **Default:** `0.25` s. Range 0.05 - 5 s.
- **What it does:** How often the optional PLC inputs (load present, reset, pause) are read.
- **If you raise / turn it on:** Higher: less traffic; reset/pause buttons feel slower.
- **If you lower / turn it off:** Lower: snappier remote reset/pause; more traffic.

### Read back every write  _(per space)_
- **Default:** `ON`.
- **What it does:** After writing the crane output, read it back and raise a PLC fault if it does not match.
- **If you raise / turn it on:** ON: detects a PLC that silently ignores or overwrites the bit. Recommended.
- **If you lower / turn it off:** OFF: one fewer network round-trip per write.

### PLC communication timeout  _(per space)_
- **Default:** `3.0` s. Range 0.5 - 30 s.
- **What it does:** Time to wait for the PLC to answer before the link is declared faulty.
- **If you raise / turn it on:** Higher: tolerates slow networks but a dead PLC is noticed later.
- **If you lower / turn it off:** Lower: faster fault detection, more false faults on slow networks.

### PLC reconnect interval  _(per space)_
- **Default:** `3.0` s. Range 0.5 - 60 s.
- **What it does:** Wait between reconnect attempts after the PLC link drops.
- **If you raise / turn it on:** Higher: less network noise.
- **If you lower / turn it off:** Lower: link restored sooner.

## Alerts & Siren

### Siren enabled  _(per space)_
- **Default:** `ON`.
- **What it does:** Sound the siren on this PC while a space is in violation (person, camera fault, latched).
- **If you raise / turn it on:** ON: audible alarm.
- **If you lower / turn it off:** OFF: silent (on-screen alerts only).

### Siren on PLC link fault
- **Default:** `ON`.
- **What it does:** Also sound the siren when the PLC link of a running space is down, because the crane can then NOT be interlocked.
- **If you raise / turn it on:** ON: you cannot miss a broken interlock.
- **If you lower / turn it off:** OFF: PLC faults are shown on screen only.

### Siren low tone
- **Default:** `900` Hz. Range 200 - 4000 Hz.
- **What it does:** Lower pitch of the two-tone siren.
- **If you raise / turn it on:** Higher pitch.
- **If you lower / turn it off:** Lower pitch.

### Siren high tone
- **Default:** `1400` Hz. Range 200 - 4000 Hz.
- **What it does:** Higher pitch of the two-tone siren.
- **If you raise / turn it on:** Higher pitch.
- **If you lower / turn it off:** Lower pitch.

### Siren tone length
- **Default:** `300` ms. Range 100 - 2000 ms.
- **What it does:** Length of each tone before it switches pitch.
- **If you raise / turn it on:** Slower warble.
- **If you lower / turn it off:** Faster, more urgent warble.

## Snapshots & Retention

### Save snapshot on violation
- **Default:** `ON`.
- **What it does:** Save a picture of the annotated frame when a person violation starts. Shown in Events and the daily summary.
- **If you raise / turn it on:** ON: evidence for every violation.
- **If you lower / turn it off:** OFF: saves disk space; no pictures in Events.

### Snapshot JPEG quality
- **Default:** `85` %. Range 30 - 100 %.
- **What it does:** JPEG quality of saved snapshots.
- **If you raise / turn it on:** Higher: sharper pictures, bigger files.
- **If you lower / turn it off:** Lower: smaller files, more compression artefacts.

### Snapshot cool-down per camera
- **Default:** `10` s. Range 0 - 300 s.
- **What it does:** Minimum time between two snapshots of the same camera.
- **If you raise / turn it on:** Higher: fewer files during repeated violations.
- **If you lower / turn it off:** Lower: more pictures; 0 = every violation.

### Keep snapshots for
- **Default:** `30` days. Range 1 - 3650 days.
- **What it does:** Snapshot files older than this are deleted automatically at start-up and once a day.
- **If you raise / turn it on:** Longer history, more disk space.
- **If you lower / turn it off:** Less disk space, shorter evidence history.

### Keep event log for
- **Default:** `180` days. Range 1 - 3650 days.
- **What it does:** Event log rows older than this are deleted automatically.
- **If you raise / turn it on:** Longer audit trail.
- **If you lower / turn it off:** Smaller database.

## Display

### Live view refresh rate
- **Default:** `10` fps. Range 1 - 30 fps.
- **What it does:** How often the live camera tiles are redrawn. Does NOT change detection.
- **If you raise / turn it on:** Smoother video, more UI CPU.
- **If you lower / turn it off:** Lighter UI, choppier video.

### Live view width
- **Default:** `640` px. Range 160 - 1920 px.
- **What it does:** Pictures are shrunk to at most this width before drawing in the live tiles.
- **If you raise / turn it on:** Sharper tiles, more UI CPU.
- **If you lower / turn it off:** Lighter UI, softer tiles.
