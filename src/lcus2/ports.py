"""Find the CH340 serial device the LCUS-2 enumerates as."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import Lcus2Error

# QinHeng / WCH, the vendor behind the CH340 on the LCUS-2.
WCH_VID = 0x1A86


@dataclass(frozen=True)
class SerialPort:
    device: str
    vid: int | None = None
    pid: int | None = None
    description: str = ""
    hwid: str = ""


def canonical_device(path: str) -> str:
    """Return a stable path so ``/dev/ttyUSB0`` and a by-id symlink share one port."""
    return os.path.realpath(path)


def is_lcus_adapter(port: SerialPort) -> bool:
    """True for a WCH CH340/CH341, which is what the LCUS-2 uses."""
    if port.vid == WCH_VID:
        return True
    text = f"{port.description} {port.hwid}".lower()
    return "ch340" in text or "ch341" in text or "1a86" in text


def list_ports() -> list[SerialPort]:
    """List serial devices the OS currently exposes."""
    from serial.tools import list_ports as tools

    found: list[SerialPort] = []
    for port in tools.comports():
        found.append(
            SerialPort(
                device=port.device,
                vid=port.vid,
                pid=port.pid,
                description=port.description or "",
                hwid=port.hwid or "",
            )
        )
    return found


def resolve_port(requested: str | None, ports: list[SerialPort] | None = None) -> str:
    """Use ``requested`` or the only attached CH340.

    macOS exposes the same adapter as ``/dev/cu.*`` and ``/dev/tty.*``. The
    call-out (``cu``) node is the one to open.
    """
    if requested:
        return requested

    available = ports if ports is not None else list_ports()
    matches = _dedupe([port for port in available if is_lcus_adapter(port)])
    if not matches:
        raise Lcus2Error(
            "No LCUS-2 serial device found. Plug in the board and set serial_path, "
            "for example /dev/cu.wchusbserial110 on macOS or /dev/ttyUSB0 on Linux."
        )
    if len(matches) > 1:
        names = ", ".join(port.device for port in matches)
        raise Lcus2Error(
            f"Multiple CH340 serial devices found ({names}). Set serial_path to the LCUS-2."
        )
    return matches[0].device


def _dedupe(ports: list[SerialPort]) -> list[SerialPort]:
    chosen: dict[str, SerialPort] = {}
    for port in ports:
        key = _device_key(port.device)
        current = chosen.get(key)
        if current is None or _callout_rank(port) > _callout_rank(current):
            chosen[key] = port
    return list(chosen.values())


def _device_key(device: str) -> str:
    name = device.rsplit("/", 1)[-1]
    for prefix in ("cu.", "tty."):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _callout_rank(port: SerialPort) -> int:
    name = port.device.rsplit("/", 1)[-1]
    if name.startswith("cu."):
        return 2
    return 1
