import asyncio

import pytest
from viam.errors import ValidationError
from viam.proto.app.robot import ComponentConfig
from viam.utils import dict_to_struct

from src.lcus2.ports import SerialPort
from src.lcus2.protocol import OP_OFF, OP_ON, frame
from src.models.relay import Lcus2Relay, parse_config
from tests.fake_serial import FakeSerial


def _config(channel, **attributes):
    attributes.setdefault("serial_path", "/dev/fake-lcus")
    attributes["channel"] = channel
    return ComponentConfig(name=f"relay-{channel}", attributes=dict_to_struct(attributes))


def test_validate_requires_channel_1_or_2():
    with pytest.raises(ValidationError):
        parse_config(_config(3))
    with pytest.raises(ValidationError):
        Lcus2Relay.validate_config(ComponentConfig(name="relay", attributes=dict_to_struct({})))


def test_validate_accepts_string_channel_and_default_baud():
    parsed = parse_config(_config(2))
    assert parsed.channel == 2
    assert parsed.baud_rate == 9600

    parsed = parse_config(
        ComponentConfig(
            name="relay-1",
            attributes=dict_to_struct({"channel": "1", "baud_rate": 9600, "serial_path": "/dev/ttyUSB0"}),
        )
    )
    assert parsed.channel == 1
    assert parsed.serial_path == "/dev/ttyUSB0"


def test_switch_positions_drive_one_channel():
    async def scenario():
        relay = Lcus2Relay.new(_config(1), {})
        try:
            assert await relay.get_number_of_positions() == (2, ("off", "on"))
            assert await relay.get_position() == 0

            await relay.set_position(1)
            assert FakeSerial.opened[0].writes[-1] == frame(1, OP_ON)

            FakeSerial.replies[b"\xff"] = b"CH1: ON\r\nCH2: OFF\r\n"
            assert await relay.get_position() == 1
            status = await relay.get_status()
            assert status["on"] is True
            assert status["channels"]["2"] is False
        finally:
            await relay.close()

    asyncio.run(scenario())


def test_position_out_of_range_is_rejected():
    async def scenario():
        relay = Lcus2Relay.new(_config(1), {})
        try:
            with pytest.raises(ValueError, match="position"):
                await relay.set_position(2)
            assert FakeSerial.opened[0].writes == []
        finally:
            await relay.close()

    asyncio.run(scenario())


def test_both_channels_share_the_port():
    async def scenario():
        first = Lcus2Relay.new(_config(1), {})
        second = Lcus2Relay.new(_config(2), {})
        try:
            assert len(FakeSerial.opened) == 1
            await first.set_position(1)
            await second.set_position(0)
            assert FakeSerial.opened[0].writes == [frame(1, OP_ON), frame(2, OP_OFF)]
            await first.close()
            assert FakeSerial.opened[0].is_open
        finally:
            await second.close()

        assert not FakeSerial.opened[0].is_open
        await second.close()

    asyncio.run(scenario())


def test_do_command_can_set_the_other_channel():
    async def scenario():
        relay = Lcus2Relay.new(_config(1), {})
        try:
            result = await relay.do_command({"command": "set", "channel": 2, "on": "true"})
            assert result == {"channel": 2, "position": 1, "on": True}
            assert frame(2, OP_ON) in FakeSerial.opened[0].writes
            assert (await relay.do_command({"command": "off"}))["position"] == 0
            assert FakeSerial.opened[0].writes[-1] == frame(1, OP_OFF)
            with pytest.raises(ValueError, match="command"):
                await relay.do_command({"command": "pulse"})
        finally:
            await relay.close()

    asyncio.run(scenario())


def test_omitted_path_uses_the_only_ch340(monkeypatch):
    monkeypatch.setattr(
        "src.lcus2.ports.list_ports",
        lambda: [SerialPort("/dev/cu.wchusbserial110", vid=0x1A86, pid=0x7523)],
    )

    async def scenario():
        relay = Lcus2Relay.new(
            ComponentConfig(name="relay-1", attributes=dict_to_struct({"channel": 1})), {}
        )
        try:
            assert relay._path == "/dev/cu.wchusbserial110"
        finally:
            await relay.close()

    asyncio.run(scenario())
