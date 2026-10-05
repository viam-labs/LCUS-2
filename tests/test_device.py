from src.lcus2.protocol import OP_OFF, OP_ON, frame
from scripts.device import main
from tests.fake_serial import FakeSerial


def _hold(monkeypatch) -> list[float]:
    held: list[float] = []

    async def sleep(seconds: float) -> None:
        held.append(seconds)

    monkeypatch.setattr("scripts.device.asyncio.sleep", sleep)
    return held


def test_cycle_holds_each_coil_for_one_second(monkeypatch, capsys):
    held = _hold(monkeypatch)
    assert main(["--path", "/dev/fake-lcus"]) == 0

    port = FakeSerial.opened[0]
    assert port.writes == [
        frame(1, OP_ON),
        b"\xff",
        frame(1, OP_OFF),
        b"\xff",
        frame(2, OP_ON),
        b"\xff",
        frame(2, OP_OFF),
        b"\xff",
    ]
    assert held == [1.0, 1.0]
    assert not port.is_open
    output = capsys.readouterr().out
    assert "using /dev/fake-lcus" in output
    assert "channel 1 on for 1s  CH1: OFF CH2: OFF" in output
    assert "channel 2 off CH1: OFF CH2: OFF" in output


def test_one_duration_applies_to_every_channel(monkeypatch):
    held = _hold(monkeypatch)
    assert main(["--path", "/dev/fake-lcus", "5"]) == 0
    assert held == [5.0, 5.0]


def test_two_durations_map_to_each_channel(monkeypatch):
    held = _hold(monkeypatch)
    assert main(["--path", "/dev/fake-lcus", "2", "4"]) == 0
    assert held == [2.0, 4.0]


def test_duration_count_must_match_selected_channels(capsys):
    assert main(["--path", "/dev/fake-lcus", "1", "2", "3"]) == 2
    assert "durations" in capsys.readouterr().err
    assert FakeSerial.opened == []


def test_status_only_does_not_switch(capsys):
    assert main(["--path", "/dev/fake-lcus", "--status"]) == 0
    assert FakeSerial.opened[0].writes == [b"\xff"]
    assert "status CH1: OFF CH2: OFF" in capsys.readouterr().out


def test_one_channel_leaves_the_other_alone(monkeypatch):
    held = _hold(monkeypatch)
    assert main(["--path", "/dev/fake-lcus", "--channel", "2", "3"]) == 0
    assert held == [3.0]
    writes = FakeSerial.opened[0].writes
    assert writes[0] == frame(2, OP_ON)
    assert frame(1, OP_ON) not in writes
    assert frame(1, OP_OFF) not in writes


def test_baud_is_passed_to_the_port():
    assert main(["--path", "/dev/fake-lcus", "--status", "--baud", "19200"]) == 0
    assert FakeSerial.opened[0].baudrate == 19200


def test_unconfirmed_coils_are_an_error(monkeypatch, capsys):
    _hold(monkeypatch)
    from tests.fake_serial import FakeSerial as port

    port.replies = {}
    assert main(["--path", "/dev/fake-lcus", "--channel", "1", "0.01"]) == 1
    assert "did not confirm" in capsys.readouterr().err


def test_missing_board_exits_without_opening_a_port(monkeypatch, capsys):
    monkeypatch.setattr("src.lcus2.ports.list_ports", lambda: [])
    assert main([]) == 1
    assert FakeSerial.opened == []
    assert "serial_path" in capsys.readouterr().err
