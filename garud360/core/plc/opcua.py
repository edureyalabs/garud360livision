# garud360/core/plc/opcua.py
"""Generic OPC UA driver (asyncua) for any PLC/gateway exposing an OPC UA server
(Siemens S7-1500, Beckhoff, B&R, Omron NX/NJ, Rockwell via gateway, ABB, Codesys, ...).

Address = OPC UA NodeId of a Boolean variable, for example:
    ns=3;s="CranePLC"."Permit"        ns=2;i=1234
Connection: opc.tcp://host:port (anonymous or user/password; security policy None).
"""
from __future__ import annotations

import threading
from typing import Any

from garud360.core.plc.base import FieldDef, PlcConfig, PlcDriver, PlcError


class OpcUaDriver(PlcDriver):
    TYPE = "opcua"
    LABEL = "OPC UA (generic - ABB, Beckhoff, Codesys, S7-1500, ...)"
    DEFAULT_PORT = 4840
    ADDRESS_HELP = 'NodeId of a Boolean variable, e.g.  ns=3;s="CranePLC"."Permit"  or  ns=2;i=1234'
    EXAMPLE_PERMIT = 'ns=2;s=Crane.Permit'
    EXTRA_FIELDS = (
        FieldDef("username", "User name (optional)", "str", "", "Leave empty for anonymous access."),
        FieldDef("password", "Password (optional)", "str", "", "Stored in the local database."),
    )
    NOTES = "Security policy 'None' only in this version. Make the variable writable for the OPC UA user."

    def __init__(self, cfg: PlcConfig, timeout_s: float = 3.0) -> None:
        super().__init__(cfg, timeout_s)
        self._client: Any = None
        self._nodes: dict[str, Any] = {}
        self._lock = threading.Lock()

    @classmethod
    def validate_address(cls, address: str) -> str | None:
        a = address.strip()
        if "=" not in a or not (a.lower().startswith(("ns=", "i=", "s=", "g=", "b="))):
            return 'Use a NodeId such as ns=2;s=Crane.Permit or ns=2;i=1234'
        return None

    @property
    def connected(self) -> bool:
        return self._client is not None

    def connect(self) -> None:
        self.close()
        try:
            from asyncua.sync import Client
        except ImportError as exc:  # pragma: no cover
            raise PlcError("The 'asyncua' package is not installed.") from exc
        host = self.cfg.host
        url = host if host.startswith("opc.tcp://") else f"opc.tcp://{host}:{self.effective_port()}"
        client = Client(url, timeout=self.timeout_s)
        user = str(self.cfg.extras.get("username", "")).strip()
        if user:
            client.set_user(user)
            client.set_password(str(self.cfg.extras.get("password", "")))
        try:
            client.connect()
        except Exception as exc:  # noqa: BLE001
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            raise PlcError(f"Cannot connect to OPC UA server {url}: {exc}") from None
        self._client = client
        self._nodes = {}

    def close(self) -> None:
        c, self._client = self._client, None
        self._nodes = {}
        if c is not None:
            try:
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def _node(self, address: str) -> Any:
        if self._client is None:
            raise PlcError("Not connected.")
        n = self._nodes.get(address)
        if n is None:
            n = self._client.get_node(address.strip())
            self._nodes[address] = n
        return n

    def write_bool(self, address: str, value: bool) -> None:
        with self._lock:
            try:
                from asyncua import ua
                node = self._node(address)
                node.write_value(ua.DataValue(ua.Variant(bool(value), ua.VariantType.Boolean)))
            except PlcError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"OPC UA write failed: {exc}") from None

    def read_bool(self, address: str) -> bool:
        with self._lock:
            try:
                return bool(self._node(address).read_value())
            except PlcError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.close()
                raise PlcError(f"OPC UA read failed: {exc}") from None
