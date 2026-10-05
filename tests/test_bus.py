import asyncio

import pytest

from src.lcus2.bus import get_bus, release_bus
from src.lcus2.errors import Lcus2Error
from src.lcus2.protocol import OP_OFF, OP_ON, OP_QUERY, frame
from tests.fake_serial import FakeSerial


def test_set_writes_the_documented_frame():
    async def scenario():
        bus = get_bus("/dev/fake-lcus", 9600, query_timeout=0.02)
        try:
            await bus.set_on(1, True)
            await bus.set_on(2, False)
        finally:
            release_bus(bus)

    asyncio.run(scenario())
    port = FakeSerial.opened[0]
    assert port.writes == [frame(1, OP_ON), frame(2, OP_OFF)]


def test_all_channel_query_parses_both_coils():
    FakeSerial.replies = {b"\xff": b"CH1: ON \r\nCH2: OFF\r\n"}

    async def scenario():
        bus = get_bus("/dev/fake-lcus", 9600, query_timeout=0.02)
        try:
            assert await bus.read_states() == {1: True, 2: False}
        finally:
            release_bus(bus)

    asyncio.run(scenario())
    assert FakeSerial.opened[0].writes == [b"\xff"]


def test_per_channel_query_is_used_when_ff_is_silent():
    FakeSerial.replies = {
        frame(1, OP_QUERY): b"CH1:ON\r\n",
        frame(2, OP_QUERY): b"CH2:OFF\r\n",
    }

    async def scenario():
        bus = get_bus("/dev/fake-lcus", 9600, query_timeout=0.02)
        try:
            assert await bus.read_states() == {1: True, 2: False}
            writes_after_discovery = len(FakeSerial.opened[0].writes)
            assert await bus.read_states() == {1: True, 2: False}
            assert FakeSerial.opened[0].writes[writes_after_discovery:] == [
                frame(1, OP_QUERY),
                frame(2, OP_QUERY),
            ]
        finally:
            release_bus(bus)

    asyncio.run(scenario())


def test_silent_board_reports_the_last_command():
    FakeSerial.replies = {}

    async def scenario():
        bus = get_bus("/dev/fake-lcus", 9600, query_timeout=0.02)
        try:
            with pytest.raises(Lcus2Error, match="No status response"):
                await bus.read_states(required=1)
            await bus.set_on(1, True)
            assert (await bus.read_states(required=1))[1] is True
            writes = len(FakeSerial.opened[0].writes)
            assert (await bus.read_states(required=1))[1] is True
            assert len(FakeSerial.opened[0].writes) == writes
        finally:
            release_bus(bus)

    asyncio.run(scenario())


def test_two_callers_share_one_port_until_the_last_release(tmp_path):
    device = tmp_path / "ttyUSB0"
    device.write_text("")
    alias = tmp_path / "by-id"
    alias.symlink_to(device)

    first = get_bus(str(device), 9600, query_timeout=0.02)
    second = get_bus(str(alias), 9600, query_timeout=0.02)
    try:
        assert first is second
        assert len(FakeSerial.opened) == 1
        assert FakeSerial.opened[0].is_open
    finally:
        release_bus(first)
        assert FakeSerial.opened[0].is_open
        release_bus(second)

    assert not FakeSerial.opened[0].is_open
