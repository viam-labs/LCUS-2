"""One shared serial session for every relay channel on a board.

Two Viam switch components (channel 1 and channel 2) open the same device.
The OS allows that only once, so this process keeps a single port and
reference-counts it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable

from .errors import Lcus2Error
from .ports import canonical_device
from .protocol import OP_OFF, OP_ON, OP_QUERY, QUERY_ALL, frame, parse_status

logger = logging.getLogger("lcus2.serial")

DEFAULT_BAUD = 9600
DEFAULT_QUERY_TIMEOUT = 0.2
_COMMAND_GAP = 0.01

_buses: dict[tuple[str, int], SerialBus] = {}
_registry_lock = threading.Lock()


def get_bus(path: str, baud: int, *, query_timeout: float = DEFAULT_QUERY_TIMEOUT) -> SerialBus:
    """Open ``path`` if this process does not already have it, and take a reference."""
    key = (canonical_device(path), baud)
    with _registry_lock:
        bus = _buses.get(key)
        created = bus is None
        if bus is None:
            bus = SerialBus(key[0], baud, query_timeout=query_timeout)
        try:
            bus.acquire()
        except Exception:
            if created:
                bus.close_port()
            raise
        if created:
            _buses[key] = bus
        return bus


def release_bus(bus: SerialBus) -> None:
    """Drop one reference. The last release closes the device."""
    with _registry_lock:
        if bus._refs <= 0:
            return
        bus._refs -= 1
        if bus._refs == 0:
            bus.close_port()
            _buses.pop((bus.path, bus.baud), None)


def reset_buses_for_tests() -> None:
    with _registry_lock:
        for bus in list(_buses.values()):
            bus.close_port()
        _buses.clear()


class SerialBus:
    """Thread-safe session for one LCUS-2."""

    def __init__(self, path: str, baud: int, *, query_timeout: float = DEFAULT_QUERY_TIMEOUT):
        self.path = path
        self.baud = baud
        self._query_timeout = query_timeout
        self._refs = 0
        self._port = None
        self._io = threading.Lock()
        self._async_lock: asyncio.Lock | None = None
        self._known: dict[int, bool] = {}
        # unknown -> try the all-channel query, then per-channel queries.
        # ff / channel -> keep using whichever form the board answered.
        # none -> the board does not answer; report the last commanded state.
        self._query_mode = "unknown"

    def acquire(self) -> None:
        """Open the device on the first reference. Caller holds the registry lock."""
        with self._io:
            if self._port is None or not getattr(self._port, "is_open", False):
                self._port = open_serial(self.path, self.baud)
                self._query_mode = "unknown"
        self._refs += 1

    def close_port(self) -> None:
        with self._io:
            port = self._port
            self._port = None
            if port is not None and getattr(port, "is_open", False):
                port.close()

    async def set_on(self, channel: int, on: bool) -> None:
        payload = frame(channel, OP_ON if on else OP_OFF)
        async with self._lock():
            await asyncio.to_thread(self._write, payload)
            self._known[channel] = on

    async def read_states(self, required: int | None = None) -> dict[int, bool]:
        """Read coil states, falling back to the last commanded state."""
        async with self._lock():
            states = await asyncio.to_thread(self._read_states)
        if required is not None and required not in states:
            raise Lcus2Error(
                f"LCUS-2 at {self.path} did not report channel {required}. "
                "Set the relay once if this board does not answer status queries."
            )
        return states

    def _lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def _write(self, payload: bytes) -> None:
        with self._io:
            port = self._require_port()
            logger.debug("TX %s %s", self.path, payload.hex(" "))
            written = port.write(payload)
            port.flush()
            if written != len(payload):
                raise Lcus2Error(f"Short write to {self.path}: sent {written} of {len(payload)} bytes")
            time.sleep(_COMMAND_GAP)

    def _read_states(self) -> dict[int, bool]:
        with self._io:
            if self._query_mode != "none":
                states = self._query()
                if states:
                    self._known.update(states)
                    return dict(self._known)
                if self._query_mode == "unknown":
                    self._query_mode = "none"
                    logger.warning(
                        "LCUS-2 at %s did not answer a status query; tracking state from commands",
                        self.path,
                    )
            if self._known:
                return dict(self._known)
            raise Lcus2Error(
                f"No status response from LCUS-2 at {self.path}. "
                "Confirm serial_path, baud 9600, and that no other program has the device open."
            )

    def _query(self) -> dict[int, bool]:
        parsed: dict[int, bool] = {}
        if self._query_mode in ("unknown", "ff"):
            parsed = parse_status(self._exchange(QUERY_ALL, lambda found: 1 in found and 2 in found))
            if 1 in parsed and 2 in parsed:
                self._query_mode = "ff"
                return parsed
            if self._query_mode == "ff":
                return parsed

        for channel in (1, 2):
            if channel in parsed:
                continue
            raw = self._exchange(frame(channel, OP_QUERY), lambda found, ch=channel: ch in found)
            for number, on in parse_status(raw).items():
                if number == channel:
                    parsed[number] = on
        if parsed:
            self._query_mode = "channel"
        return parsed

    def _exchange(self, payload: bytes, done: Callable[[dict[int, bool]], bool]) -> bytes:
        port = self._require_port()
        try:
            port.reset_input_buffer()
        except Exception:
            logger.debug("reset_input_buffer failed on %s", self.path, exc_info=True)
        logger.debug("TX %s %s", self.path, payload.hex(" "))
        written = port.write(payload)
        port.flush()
        if written != len(payload):
            raise Lcus2Error(f"Short write to {self.path}: sent {written} of {len(payload)} bytes")
        return self._read_until(port, done)

    def _read_until(self, port, done: Callable[[dict[int, bool]], bool]) -> bytes:
        deadline = time.monotonic() + self._query_timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = port.read(64)
            if chunk:
                buf.extend(chunk)
                if done(parse_status(buf)):
                    logger.debug("RX %s %s", self.path, bytes(buf).hex(" "))
                    return bytes(buf)
            else:
                time.sleep(0.005)
        if buf:
            logger.debug("RX %s %s", self.path, bytes(buf).hex(" "))
        return bytes(buf)

    def _require_port(self):
        port = self._port
        if port is None or not getattr(port, "is_open", False):
            raise Lcus2Error(f"Serial port {self.path} is not open")
        return port


def open_serial(path: str, baud: int):
    """Open a CH340 in raw 8N1. DTR and RTS stay low so opening does not pulse the coils."""
    import serial

    port = serial.Serial()
    port.port = path
    port.baudrate = baud
    port.bytesize = serial.EIGHTBITS
    port.parity = serial.PARITY_NONE
    port.stopbits = serial.STOPBITS_ONE
    port.timeout = 0.05
    port.write_timeout = 1.0
    port.xonxoff = False
    port.rtscts = False
    port.dsrdtr = False
    port.dtr = False
    port.rts = False
    try:
        port.exclusive = True
    except Exception:
        logger.debug("exclusive mode is unavailable", exc_info=True)

    try:
        port.open()
    except serial.SerialException as exc:
        if getattr(port, "exclusive", False) and _exclusive_unsupported(exc):
            port.exclusive = False
            try:
                port.open()
            except serial.SerialException as retry:
                raise Lcus2Error(_open_failure(path, retry)) from retry
        else:
            raise Lcus2Error(_open_failure(path, exc)) from exc

    # The CH340 drops the first bytes written immediately after open.
    time.sleep(0.05)
    try:
        port.reset_input_buffer()
    except Exception:
        logger.debug("reset_input_buffer after open failed", exc_info=True)
    return port


def _exclusive_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return "exclusive" in text or "inappropriate ioctl" in text or "invalid argument" in text


def _open_failure(path: str, exc: Exception) -> str:
    text = str(exc).lower()
    hint = ""
    if "permission" in text:
        hint = " On Linux, add your user to the dialout group and log in again: sudo usermod -aG dialout $USER"
    elif "no such file" in text or "not found" in text or "failed to open" in text:
        hint = (
            " On macOS, look for /dev/cu.wchusbserial* or /dev/cu.usbserial*. "
            "On Linux, look for /dev/ttyUSB*."
        )
    return f"Could not open LCUS-2 serial port {path}: {exc}.{hint}"
