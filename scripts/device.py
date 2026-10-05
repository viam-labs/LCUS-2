"""Pulse an attached LCUS-2 from the command line.

Each selected coil is turned on, held, then turned off. The default hold is
1 second. ``./device.sh --status`` only reads.

Examples::

    ./device.sh
    ./device.sh 5
    ./device.sh 2 4
    ./device.sh --channel 1 3
    ./device.sh --status
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

from src.lcus2.bus import DEFAULT_BAUD, get_bus, release_bus
from src.lcus2.errors import Lcus2Error
from src.lcus2.ports import resolve_port


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        path = resolve_port(args.path, baud=args.baud)
    except Lcus2Error as exc:
        print(exc, file=sys.stderr)
        return 1

    channels = _channels(args.channel)
    try:
        durations = _durations(channels, args.seconds)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"using {path}", flush=True)
    try:
        bus = get_bus(path, args.baud)
    except Lcus2Error as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        asyncio.run(_exercise(bus, channels, durations, status_only=args.status))
    except Lcus2Error as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        release_bus(bus)
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exercise an attached LCUS-2. Each selected coil is turned on, held, then turned off.",
    )
    parser.add_argument(
        "seconds",
        nargs="*",
        type=float,
        help="Seconds to hold each coil on. One number applies to every selected channel. "
        "Two numbers are channel 1, then channel 2. Default is 1 second each.",
    )
    parser.add_argument(
        "--path",
        help="Serial device. When omitted, use the only CH340, or the one that answers a status query.",
    )
    parser.add_argument(
        "--channel",
        type=int,
        choices=(1, 2),
        action="append",
        help="Coil to exercise. Repeat to select both. Defaults to channel 1 and channel 2.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate (default {DEFAULT_BAUD}).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read coil states without switching them.",
    )
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("--baud must be a positive integer")
    if any(seconds <= 0 for seconds in args.seconds):
        parser.error("seconds must be positive")
    return args


def _durations(channels: Sequence[int], seconds: Sequence[float]) -> tuple[float, ...]:
    if not seconds:
        return tuple(1.0 for _ in channels)
    if len(seconds) == 1:
        return tuple(float(seconds[0]) for _ in channels)
    if len(seconds) != len(channels):
        raise ValueError(
            f"expected 1 duration or {len(channels)} durations for {len(channels)} channels, "
            f"got {len(seconds)}"
        )
    return tuple(float(value) for value in seconds)


def _channels(selected: Sequence[int] | None) -> tuple[int, ...]:
    if not selected:
        return (1, 2)
    chosen: list[int] = []
    for channel in selected:
        if channel not in chosen:
            chosen.append(channel)
    return tuple(chosen)


async def _exercise(
    bus,
    channels: Sequence[int],
    durations: Sequence[float],
    *,
    status_only: bool,
) -> None:
    if status_only:
        print(f"status {_format_states(await bus.read_states())}")
        return
    for channel, seconds in zip(channels, durations):
        await bus.set_on(channel, True)
        try:
            states = await _confirmed(bus)
        except Lcus2Error:
            await bus.set_on(channel, False)
            raise
        print(f"channel {channel} on for {_format_seconds(seconds)}s  {_format_states(states)}")
        await asyncio.sleep(seconds)
        await bus.set_on(channel, False)
        print(f"channel {channel} off {_format_states(await _confirmed(bus))}")


async def _confirmed(bus):
    """Return coil states the board itself reported."""
    states = await bus.read_states()
    if getattr(bus, "_query_mode", "") == "none":
        raise Lcus2Error(
            "The board did not confirm the coil states. The printed result would only "
            "repeat the command, and the relay may still be on. Unplug the board, plug "
            "it back in, and try again."
        )
    return states


def _format_seconds(seconds: float) -> str:
    if seconds == int(seconds):
        return str(int(seconds))
    return str(seconds)


def _format_states(states: dict[int, bool]) -> str:
    if not states:
        return "no status"
    return " ".join(
        f"CH{number}: {'ON' if energized else 'OFF'}"
        for number, energized in sorted(states.items())
    )


if __name__ == "__main__":
    sys.exit(main())
