"""LCUS-2 serial frames.

The board speaks 9600 8N1. A command is four raw bytes, not ASCII hex::

    start (0xA0), channel (0x01 or 0x02), operation, checksum

The checksum is the low byte of the sum of the first three bytes.
The documented LCUS-2 commands are:

    channel 1 on:  A0 01 01 A2
    channel 1 off: A0 01 00 A1
    channel 2 on:  A0 02 01 A3
    channel 2 off: A0 02 00 A2

A single 0xFF byte asks for both coil states. The board replies with ASCII
such as ``CH1: ON \\r\\nCH2: OFF\\r\\n`` (about 20 bytes). Some clones instead
answer a per-channel query, which is the same frame with operation 0x02.
"""

from __future__ import annotations

import re

START = 0xA0
OP_OFF = 0x00
OP_ON = 0x01
OP_QUERY = 0x02
QUERY_ALL = b"\xff"

_STATUS = re.compile(rb"CH\s*(\d+)\s*:\s*(ON|OFF)", re.IGNORECASE)


def frame(channel: int, operation: int) -> bytes:
    """Build a four-byte LCUS-2 command."""
    if channel not in (1, 2):
        raise ValueError(f"channel must be 1 or 2, got {channel}")
    if operation not in (OP_OFF, OP_ON, OP_QUERY):
        raise ValueError(f"unsupported operation {operation:#x}")
    checksum = (START + channel + operation) & 0xFF
    return bytes((START, channel, operation, checksum))


def parse_status(payload: bytes) -> dict[int, bool]:
    """Return ``{channel: energized}`` for every ``CHn: ON|OFF`` field in payload."""
    states: dict[int, bool] = {}
    for match in _STATUS.finditer(payload):
        states[int(match.group(1))] = match.group(2).upper() == b"ON"
    return states
