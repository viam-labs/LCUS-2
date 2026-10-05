"""Viam switch model for one channel of an LCUS-2 USB relay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from viam.components.switch import Switch
from viam.errors import ValidationError
from viam.proto.app.robot import ComponentConfig
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import ResourceName
from viam.utils import value_to_primitive

from ..lcus2.bus import DEFAULT_BAUD, SerialBus, get_bus, release_bus
from ..lcus2.errors import Lcus2Error
from ..lcus2.ports import resolve_port

POSITIONS: tuple[str, ...] = ("off", "on")


@dataclass(frozen=True)
class RelayConfig:
    channel: int
    serial_path: str | None
    baud_rate: int


class Lcus2Relay(Switch, EasyResource):
    """One coil of an LCUS-2, exposed as a two-position switch.

    Position 0 is off and position 1 is on. Add a second switch component with
    ``channel`` 2 for the other coil. Both components can use the same
    ``serial_path``; the module opens the device once.
    """

    MODEL = "viam-labs:lcus-2:relay"

    def __init__(self, name: str):
        super().__init__(name)
        self._bus: SerialBus | None = None
        self._channel = 1
        self._path = ""
        self._baud = DEFAULT_BAUD

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Lcus2Relay:
        relay = super().new(config, dependencies)
        relay.reconfigure(config, dependencies)
        return relay

    @classmethod
    def validate_config(cls, config: ComponentConfig) -> tuple[Sequence[str], Sequence[str]]:
        parse_config(config)
        return [], []

    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> None:
        parsed = parse_config(config)
        path = resolve_port(parsed.serial_path)
        bus = get_bus(path, parsed.baud_rate)
        old = self._bus
        self._bus = bus
        self._channel = parsed.channel
        self._path = bus.path
        self._baud = parsed.baud_rate
        if old is not None:
            release_bus(old)
        self.logger.info(
            "LCUS-2 channel %s on %s at %s baud", self._channel, self._path, self._baud
        )

    async def get_position(self, *, extra: Mapping[str, Any] | None = None, timeout: float | None = None, **kwargs) -> int:
        states = await self._require_bus().read_states(required=self._channel)
        return 1 if states[self._channel] else 0

    async def set_position(
        self,
        position: int,
        *,
        extra: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        **kwargs,
    ) -> None:
        if position not in (0, 1):
            raise ValueError(f"position must be 0 (off) or 1 (on), got {position}")
        await self._require_bus().set_on(self._channel, position == 1)

    async def get_number_of_positions(
        self, *, extra: Mapping[str, Any] | None = None, timeout: float | None = None, **kwargs
    ) -> tuple[int, Sequence[str]]:
        return len(POSITIONS), POSITIONS

    async def get_status(self, *, timeout: float | None = None, **kwargs) -> Mapping[str, Any]:
        states = await self._require_bus().read_states(required=self._channel)
        return _status(self._channel, self._path, self._baud, states)

    async def do_command(
        self, command: Mapping[str, Any], *, timeout: float | None = None, **kwargs
    ) -> Mapping[str, Any]:
        name = str(command.get("command", command.get("cmd", ""))).lower()
        bus = self._require_bus()
        if name in ("status", "get"):
            states = await bus.read_states()
            return _status(self._channel, self._path, self._baud, states)
        if name == "on":
            await self.set_position(1)
            return {"channel": self._channel, "position": 1, "on": True}
        if name == "off":
            await self.set_position(0)
            return {"channel": self._channel, "position": 0, "on": False}
        if name == "set":
            channel = _command_channel(command, self._channel)
            on = _command_on(command)
            await bus.set_on(channel, on)
            return {"channel": channel, "position": 1 if on else 0, "on": on}
        raise ValueError("command must be one of: status, on, off, set")

    async def close(self) -> None:
        bus = self._bus
        self._bus = None
        if bus is not None:
            release_bus(bus)
        self.logger.debug("%s closed", self.name)

    def _require_bus(self) -> SerialBus:
        if self._bus is None:
            raise Lcus2Error(f"{self.name} is closed")
        return self._bus


def parse_config(config: ComponentConfig) -> RelayConfig:
    channel_raw = _attribute(config, "channel")
    if isinstance(channel_raw, bool) or channel_raw is None or channel_raw == "":
        raise ValidationError("channel is required and must be 1 or 2")
    try:
        channel = int(channel_raw)
    except (TypeError, ValueError):
        raise ValidationError("channel must be 1 or 2") from None
    if channel not in (1, 2) or (isinstance(channel_raw, float) and channel_raw != channel):
        raise ValidationError("channel must be 1 or 2")

    path_raw = _attribute(config, "serial_path")
    serial_path: str | None
    if path_raw is None or path_raw == "":
        serial_path = None
    elif isinstance(path_raw, str):
        serial_path = path_raw.strip() or None
    else:
        raise ValidationError("serial_path must be a string")

    baud_raw = _attribute(config, "baud_rate")
    if baud_raw is None or baud_raw == "":
        baud = DEFAULT_BAUD
    elif isinstance(baud_raw, bool):
        raise ValidationError("baud_rate must be a positive integer")
    else:
        try:
            baud = int(baud_raw)
        except (TypeError, ValueError):
            raise ValidationError("baud_rate must be a positive integer") from None
        if baud <= 0 or (isinstance(baud_raw, float) and baud_raw != baud):
            raise ValidationError("baud_rate must be a positive integer")

    return RelayConfig(channel=channel, serial_path=serial_path, baud_rate=baud)


def _attribute(config: ComponentConfig, key: str) -> Any:
    value = config.attributes.fields.get(key)
    if value is None:
        return None
    return value_to_primitive(value)


def _command_channel(command: Mapping[str, Any], default: int) -> int:
    raw = command.get("channel", default)
    try:
        channel = int(raw)
    except (TypeError, ValueError):
        raise ValueError("channel must be 1 or 2") from None
    if channel not in (1, 2):
        raise ValueError("channel must be 1 or 2")
    return channel


def _command_on(command: Mapping[str, Any]) -> bool:
    if "on" in command:
        return _as_bool(command["on"])
    if "position" in command:
        try:
            position = int(command["position"])
        except (TypeError, ValueError):
            raise ValueError("position must be 0 (off) or 1 (on)") from None
        if position not in (0, 1):
            raise ValueError("position must be 0 (off) or 1 (on)")
        return position == 1
    raise ValueError("set requires 'on' or 'position'")


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "on", "yes"):
            return True
        if lowered in ("0", "false", "off", "no"):
            return False
        raise ValueError("on must be true or false")
    return bool(value)


def _status(channel: int, path: str, baud: int, states: dict[int, bool]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "serial_path": path,
        "baud_rate": baud,
        "channel": channel,
        "channels": {str(number): energized for number, energized in sorted(states.items())},
    }
    on = states.get(channel)
    if on is not None:
        payload["position"] = 1 if on else 0
        payload["on"] = on
    return payload
