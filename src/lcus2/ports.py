"""Find the CH340 serial device the LCUS-2 enumerates as."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Callable

from .errors import Lcus2Error

# QinHeng / WCH, the vendor behind the CH340 on the LCUS-2.
WCH_VID = 0x1A86
_IDENTIFY_TIMEOUT = 0.25

logger = logging.getLogger("lcus2.ports")


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


def resolve_port(
    requested: str | None,
    ports: list[SerialPort] | None = None,
    *,
    baud: int = 9600,
    identify: Callable[[str, int], bool] | None = None,
) -> str:
    """Use ``requested``, the only CH340, or the one CH340 that answers a status query.

    macOS exposes the same adapter as ``/dev/cu.*`` and ``/dev/tty.*``. The
    call-out (``cu``) node is the one to open. Identifying a board opens the
    port, so that step runs on Linux only: closing a CH340 on macOS can leave
    the chip silent.
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
    if len(matches) == 1:
        return matches[0].device

    names = ", ".join(port.device for port in matches)
    if identify is None and sys.platform == "darwin":
        raise Lcus2Error(
            f"Multiple CH340 serial devices found ({names}). Set serial_path to the LCUS-2."
        )
    checker = identify or _answers_status
    answered = [port for port in matches if _checked(checker, port.device, baud)]
    if len(answered) == 1:
        logger.info(
            "Using %s: it answered an LCUS-2 status query (%s)",
            answered[0].device,
            names,
        )
        return answered[0].device
    if not answered:
        raise Lcus2Error(
            f"Multiple CH340 serial devices found ({names}), and none answered an LCUS-2 "
            "status query. Set serial_path to the LCUS-2."
        )
    found = ", ".join(port.device for port in answered)
    raise Lcus2Error(
        f"Multiple LCUS-2 boards answered ({found}). Set serial_path to the one this component should use."
    )


def _checked(identify: Callable[[str, int], bool], device: str, baud: int) -> bool:
    try:
        return bool(identify(device, baud))
    except Exception:
        logger.debug("could not identify %s", device, exc_info=True)
        return False


def _answers_status(device: str, baud: int) -> bool:
    """True when ``device`` replies with both LCUS-2 coil states."""
    from .bus import open_serial
    from .protocol import OP_QUERY, QUERY_ALL, frame, parse_status

    try:
        port = open_serial(device, baud)
    except Exception:
        logger.debug("could not open %s to identify it", device, exc_info=True)
        return False
    try:
        states = _read_states(
            port, QUERY_ALL, parse_status, lambda found: 1 in found and 2 in found
        )
        if 1 in states and 2 in states:
            return True
        for channel in (1, 2):
            if channel in states:
                continue
            found = _read_states(
                port,
                frame(channel, OP_QUERY),
                parse_status,
                lambda got, number=channel: number in got,
            )
            if channel in found:
                states[channel] = found[channel]
        return 1 in states and 2 in states
    finally:
        try:
            port.close()
        except Exception:
            logger.debug("close after identify failed for %s", device, exc_info=True)


def _read_states(port, payload: bytes, parse_status, done: Callable[[dict[int, bool]], bool]) -> dict[int, bool]:
    try:
        port.reset_input_buffer()
    except Exception:
        logger.debug("reset_input_buffer during identify failed", exc_info=True)
    port.write(payload)
    port.flush()
    deadline = time.monotonic() + _IDENTIFY_TIMEOUT
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = port.read(64)
        if not chunk:
            time.sleep(0.005)
            continue
        buf.extend(chunk)
        states = parse_status(buf)
        if done(states):
            return states
    return parse_status(buf)


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
