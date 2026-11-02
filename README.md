<!-- README.md -->
# Garud 360 Li-Vision

Computer-vision (YOLO26) crane-zone safety monitoring for Windows, with a 3D LiDAR tab reserved for a later release.

A **space** is one monitored area: up to **10 live camera sources** and one **crane output channel**. If a person
(confidence >= 0.40 by default) is inside the danger zone - or a camera fails - the app blocks crane movement through the
PLC (the "holder knob" / run-permissive is released) and un-blocks it when the zone is clear. Up to **50 spaces**.

## Features

| Area | What you get |
|---|---|
| Login | Local username/password (bcrypt). Admin and Operator roles. No cloud sign-in. |
| Spaces | Up to 50 spaces, each with up to 10 cameras. Start/stop each space independently. |
| Cameras | DroidCam (Android/iPhone: IP + port + **Connect** test), laptop/USB cameras, RTSP IP cameras, HTTP/MJPEG, video files (for testing). Automatic reconnect with back-off. |
| Detection | YOLO26 (segment or detect, sizes n/s/m/l/x, custom/exported models), person-only, trigger/release frames, per-camera polygon **monitored zone**. One shared, fair scheduler for all cameras. |
| Fail-safe | A lost, frozen or stalled camera (or a stalled detector) is treated exactly like a detected person and blocks the crane. Crane output is blocked first and only released once all cameras are proven healthy. |
| Crane output | Siemens S7, Rockwell/Allen-Bradley (EtherNet/IP), Mitsubishi MELSEC (MC), Omron (FINS), Schneider (Modbus TCP), plus generic OPC UA - and a **built-in simulated crane**. Heartbeat, write read-back, auto-reconnect. |
| Client requirements | AI only while a load is suspended (PLC "load present" input), latch-until-**manual reset** (app button or crane remote input), **pause** AI to attach/detach a load with automatic resume, siren, violation snapshots, daily violation summary. |
| Dashboard | All spaces, filters, live camera grid with overlays, animated crane simulation, alarm banner, engine load meter, event log with snapshots, CSV export. |
| Settings console | Every number (confidence, frames, FPS, model, timeouts, ...) with defaults, per-space overrides and a built-in guide: [docs/SETTINGS_GUIDE.md](docs/SETTINGS_GUIDE.md). |

## Default login (first run)

| Username | Password |
|---|---|
| `admin` | `Garud@360` |

* You are asked to choose a new password at the first sign-in.
* The factory values live in **`garud360/config/defaults.py`** (`DEFAULT_ADMIN_USERNAME`, `DEFAULT_ADMIN_PASSWORD`,
  `FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN`). They are only used to create the first account when the database is empty.
* Later, manage users in the app: **Users** page (admin).
* Forgot the admin password? Run `.venv\Scripts\python -m garud360 --reset-admin` - it restores the factory login.

## Install on Windows

### Option A - run from source (recommended while we iterate; supports NVIDIA GPU)

1. Install **Python 3.11 (64-bit)** from <https://www.python.org/downloads/windows/> and tick *Add python.exe to PATH*.
2. Install **Git** from <https://git-scm.com/download/win> (or use *Code > Download ZIP* on GitHub and unzip).
3. Open *Command Prompt* and run (if the repository is private, Git for Windows opens a browser window to sign in to GitHub):

```bat
git clone -b claude/vigilant-volta-bybkpf https://github.com/edureyalabs/garud360livision.git
cd garud360livision
scripts\setup_windows.bat
```

4. Start the app with the **Garud 360 Li-Vision** desktop shortcut (created by the setup), or `scripts\run_garud360.bat`.
   If something fails, `scripts\run_garud360_console.bat` shows the error messages.

The first start downloads the YOLO26 model (~25 MB for the default `yolo26n-seg`), so the PC needs internet once.
You can also do it from **Settings > Download / verify model**.

**Update later:** `scripts\update_windows.bat` (runs `git pull` and refreshes the packages). Your data is kept.

**GPU:** when `setup_windows.bat` asks about an NVIDIA GPU answer `y`, then set **Settings > Inference device = cuda:0**.

### Option B - installer (.exe)

When a version tag (for example `v1.0.0`) is pushed, GitHub Actions builds `Garud360LiVision-Setup.exe` and attaches it to
the **Releases** page (also available as a workflow artifact under *Actions > Build Windows installer*).
The installer build bundles the CPU version of PyTorch.

## First-time walkthrough (10 minutes, no PLC needed)

1. Sign in and change the password.
2. **Spaces > + New space**. Name it. On **Cameras** press *Add camera*:
   * *DroidCam*: open DroidCam on the phone, type the IP and port it shows, press **Connect / Test** - you should see a picture.
   * *Laptop / USB camera*: press *Scan for cameras*, pick one, **Connect / Test**.
   * Optional: **Draw monitored zone...** to count only people inside the danger area.
3. **Output channel** stays *Simulated crane (built-in)* for now. Save.
4. **Dashboard**: press **Start** on the space, then **Open live view**. Step in front of the camera: the crane stops, the
   siren sounds and an event with a snapshot is stored. Step away: the crane resumes.
5. Unplug / close the camera stream: the space shows **CAMERA FAULT** and the crane stays blocked.
6. Tune values in **Settings** (each setting explains what happens if you raise or lower it).

## Safety notice (please read)

* This is an **assist** layer. It is not a certified safety function (no SIL/PL rating) and must not replace hard-wired
  safety circuits, e-stops, or site procedures. Validate every installation with a qualified engineer.
* The PLC must contain a **watchdog on the heartbeat bit**: if it stops toggling (app crash, PC off, cable pulled) the
  PLC must block the crane by itself. See [docs/PLC_INTEGRATION.md](docs/PLC_INTEGRATION.md).
* Vision limits: poor light, glare, occlusion, camera angle and distance reduce detection. Test with real people at the
  real site and tune the confidence, zone and frame counts.
* Monitoring stops when the app closes. By default that **blocks** the crane (`Block crane when monitoring stops`).

## Where is my data?

`%LOCALAPPDATA%\Garud360LiVision\` : `garud360.db` (users, spaces, events, settings), `snapshots\`, `models\`, `logs\`.
Back up the folder to move to another PC.

## Troubleshooting

| Problem | Fix |
|---|---|
| DroidCam will not connect | Close other viewers of the stream (browser tab / second PC), phone and PC on the same Wi-Fi, allow `python.exe` through Windows Firewall (private networks), correct IP/port. |
| "Detection engine: ERROR" on the dashboard | Open **Settings > Download / verify model** to see the message (usually no internet for the first download, or a wrong custom model path). |
| Everything is slow / "OVERLOADED" | Lower **Detection speed per camera**, use model size `n`, switch the model type to `detect`, reduce image size, or use an NVIDIA GPU. |
| Spaces show CAMERA FAULT: "Detection stalled" | The machine cannot keep up (see above) or the model failed to load. |
| Start-up takes a few seconds with no window | PyTorch is loading (it must load before the UI on Windows). Normal. |
| Another copy is already running | Only one instance may control the cranes. Close the other one. |

Logs: `%LOCALAPPDATA%\Garud360LiVision\logs\garud360.log`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest                                        # tests use fake cameras / fake PLC servers
python scripts/generate_settings_guide.py               # after editing garud360/config/settings_schema.py
python -m garud360 --data-dir ./.devdata                # run with a throw-away data folder
GARUD360_E2E_IMAGE=photo_with_people.jpg python -m pytest tests/test_e2e_real_model.py -s   # real YOLO26 end-to-end
```

Layout: `garud360/core` (cameras, detection, interlock, PLC drivers, runtime), `garud360/ui` (Qt screens),
`garud360/db` (SQLite), `garud360/auth`, `garud360/config` (defaults + settings schema), `tests`, `packaging`, `scripts`, `docs`.

Release: bump `garud360/__init__.py` version, then `git tag v1.0.1 && git push origin v1.0.1`.
