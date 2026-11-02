# garud360/core/plc/registry.py
"""Catalogue of supported PLC families."""
from __future__ import annotations

from typing import Any

from garud360.core.plc.base import PlcConfig, PlcDriver, PlcError
from garud360.core.plc.mitsubishi import MitsubishiMcDriver
from garud360.core.plc.modbus import ModbusTcpDriver
from garud360.core.plc.omron import OmronFinsDriver
from garud360.core.plc.opcua import OpcUaDriver
from garud360.core.plc.rockwell import RockwellCipDriver
from garud360.core.plc.siemens import SiemensS7Driver
from garud360.core.plc.simulated import SimulatedPlcDriver

DRIVERS: dict[str, type[PlcDriver]] = {d.TYPE: d for d in (
    SimulatedPlcDriver, SiemensS7Driver, RockwellCipDriver, MitsubishiMcDriver, OmronFinsDriver,
    ModbusTcpDriver, OpcUaDriver)}


def driver_class(type_name: str) -> type[PlcDriver]:
    try:
        return DRIVERS[type_name]
    except KeyError:
        raise PlcError(f"Unknown PLC type '{type_name}'.") from None


def create_driver(cfg: PlcConfig, timeout_s: float = 3.0) -> PlcDriver:
    return driver_class(cfg.type)(cfg, timeout_s)


def validate(cfg_dict: dict[str, Any]) -> list[str]:
    cfg = PlcConfig.from_dict(cfg_dict)
    if cfg.type not in DRIVERS:
        return ["Choose an output channel type."]
    return driver_class(cfg.type).validate_config(cfg)


def check_connection(cfg_dict: dict[str, Any], timeout_s: float = 4.0) -> tuple[bool, str]:
    """Connect and READ the crane output bit. Never writes, so it cannot move or block a real crane."""
    cfg = PlcConfig.from_dict(cfg_dict)
    errs = validate(cfg_dict)
    if errs:
        return False, errs[0]
    drv = create_driver(cfg, timeout_s)
    try:
        drv.connect()
        try:
            val = drv.read_bool(cfg.permit_address)
            return True, f"Connected. Output bit '{cfg.permit_address}' currently reads {int(val)}."
        except PlcError as exc:
            return True, f"Connected, but reading '{cfg.permit_address}' failed: {exc}"
    except PlcError as exc:
        return False, str(exc)
    finally:
        drv.close()
        dispose = getattr(drv, "dispose", None)
        if dispose:
            dispose()
