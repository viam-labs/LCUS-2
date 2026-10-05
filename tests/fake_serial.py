"""In-memory serial port for driver tests."""

from __future__ import annotations


class FakeSerial:
    replies: dict[bytes, bytes] = {}
    opened: list[FakeSerial] = []

    def __init__(self, port: str, baudrate: int = 9600, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.is_open = True
        self.writes: list[bytes] = []
        self._inbox = bytearray()
        FakeSerial.opened.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.replies = {b"\xff": b"CH1: OFF\r\nCH2: OFF\r\n"}
        cls.opened = []

    def write(self, data: bytes) -> int:
        payload = bytes(data)
        self.writes.append(payload)
        reply = self.replies.get(payload)
        if reply:
            self._inbox.extend(reply)
        return len(payload)

    def read(self, size: int = 1) -> bytes:
        if not self._inbox:
            return b""
        count = max(1, size)
        chunk = bytes(self._inbox[:count])
        del self._inbox[:count]
        return chunk

    def flush(self) -> None:
        return None

    def reset_input_buffer(self) -> None:
        self._inbox.clear()

    def close(self) -> None:
        self.is_open = False
