<!-- docs/PLC_INTEGRATION.md -->
# PLC integration guide

Garud 360 Li-Vision talks to the crane PLC with one **output bit** (plus optional extras). Everything is configured per
space under **Spaces > Edit > Output channel (PLC)**.

## Signals

| Signal | Direction | Required | Meaning |
|---|---|---|---|
| **Crane output** | app -> PLC | yes | *Run permissive* (default): `1` = crane may move, `0` = **BLOCK** (holder knob / hold-to-run released). Switch to *Halt command* (`1` = block) if your logic needs that. |
| Heartbeat | app -> PLC | strongly recommended | Toggles `0/1/0/1...` every *PLC heartbeat interval* (default 1 s). |
| Blocked lamp / horn | app -> PLC | no | `1` while the app is blocking. |
| Load present | PLC -> app | no | `1` while a load is suspended. If configured, AI monitors **only** while it is `1` (client requirement). Unknown/unreadable = monitor anyway. |
| Reset | PLC -> app | no | Rising edge = manual reset of a latched violation (crane tab / wireless remote). Ignored while a person is still in the zone. |
| Pause | PLC -> app | no | Rising edge = pause AI for the default pause length (attach/detach a load). Auto-resumes. |

The app re-sends the crane output at every heartbeat interval, reads it back after each write (*Read back every write*),
and reconnects automatically. While the PLC link is down the space shows **PLC LINK DOWN** and the siren sounds, because the
crane can no longer be interlocked.

## Recommended PLC logic (the part that makes it fail-safe)

```
HB_CHANGED   := edge detect on heartbeat bit (rising or falling)
HB_OK        := TON-style watchdog, reset by HB_CHANGED, preset 3 x heartbeat interval (e.g. 3 s) - OK while NOT timed out
CRANE_ENABLE := APP_PERMIT AND HB_OK AND <your existing safety / hold-to-run conditions>
```

Use `CRANE_ENABLE` in series with the holder-knob / hold-to-run circuit so the crane stops if the app, the PC or the
network fails. Do **not** rely on the app alone.

## Supported families

| Family | Setting | Address examples | Notes |
|---|---|---|---|
| Siemens S7-1200/1500/300 | `Siemens S7` | `DB10.DBX0.0`, `M10.2`, `Q0.1` (`I0.0` input only) | TIA Portal: *Permit access with PUT/GET*; data block *Optimized block access* **off**. Rack 0 / slot 1 (S7-1200/1500), slot 2 (S7-300). Port 102. Bits are written with a true single-bit write. |
| Rockwell / Allen-Bradley ControlLogix, CompactLogix | `Rockwell` | `Crane_Permit`, `Crane.Permit`, `Program:Main.Permit` | EtherNet/IP port 44818. Create BOOL tags with External Access Read/Write. CPU slot (0 for CompactLogix). |
| Mitsubishi MELSEC iQ-R / iQ-F / Q / L | `Mitsubishi` | `M100`, `L50`, `Y10`, `X20`, `B1F` | X/Y/B are hexadecimal. GX Works: open the Ethernet port for MC protocol (TCP, binary), enable *Write at RUN*. Select the CPU series. |
| Omron CJ/CP/CS/CK (FINS), NJ/NX with FINS | `Omron` | `W10.05`, `CIO100.00`, `H5.01`, `A20.03`, `D100.07` | FINS/UDP port 9600. Node numbers default to the last IP octet; override in the extra fields if your network uses different node addresses. |
| Schneider Electric M221/M241/M251/M340/M580 and any Modbus TCP device | `Schneider / Modbus TCP` | `C100`, `DI5`, `HR20.3` | Port 502, unit id (default 1). Addresses are 0-based as on the wire. M221/M241: `%M0` = coil 0, `%MW0` = holding register 0. |
| Anything with an OPC UA server (ABB, Beckhoff, Codesys, B&R, S7-1500 OPC UA, ...) | `OPC UA` | `ns=2;s=Crane.Permit` | `opc.tcp://host:4840`, anonymous or user/password, security policy None (v1). Variable must be Boolean and writable. |
| Built-in simulated crane | `Simulated crane` | - | For testing. Has a heartbeat watchdog and optional "monitor only with load" mode. |

**Test connection** only *connects and reads* the output bit - it never writes, so it cannot move or block a real crane.

## Commissioning checklist

1. Test with the simulated crane first, then connect the real PLC with the crane **isolated / in a safe state**.
2. Press *Test connection*; confirm the bit reads what you expect.
3. Start the space; verify the PLC bit follows (person -> BLOCK, clear -> permit).
4. Pull the network cable / kill the app: verify the PLC watchdog blocks the crane.
5. Unplug a camera: verify the crane blocks and the siren sounds.
6. Walk into the real zone in real lighting; tune confidence, zone and frame counts; record the result.
