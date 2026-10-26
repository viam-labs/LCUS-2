import os

import pytest

from src.lcus2.errors import Lcus2Error
from src.lcus2.ports import SerialPort, canonical_device, is_lcus_adapter, resolve_port


def test_wch_vid_and_description_match():
    assert is_lcus_adapter(SerialPort("/dev/ttyUSB0", vid=0x1A86, pid=0x7523))
    assert is_lcus_adapter(SerialPort("/dev/cu.wchusbserial110", description="USB Serial CH340"))
    assert not is_lcus_adapter(SerialPort("/dev/ttyACM0", vid=0x2341, description="Arduino"))


def test_explicit_path_is_used_as_given():
    assert resolve_port("/dev/ttyUSB0", ports=[]) == "/dev/ttyUSB0"


def test_single_ch340_is_selected_and_callout_node_wins():
    ports = [
        SerialPort("/dev/tty.wchusbserial110", vid=0x1A86),
        SerialPort("/dev/cu.wchusbserial110", vid=0x1A86),
        SerialPort("/dev/ttyACM0", vid=0x2341, description="Arduino"),
    ]
    assert resolve_port(None, ports=ports) == "/dev/cu.wchusbserial110"


def test_missing_board_explains_how_to_set_the_path():
    with pytest.raises(Lcus2Error, match="serial_path"):
        resolve_port(None, ports=[])


def test_multiple_adapters_must_be_disambiguated():
    ports = [
        SerialPort("/dev/ttyUSB0", vid=0x1A86),
        SerialPort("/dev/ttyUSB1", vid=0x1A86),
    ]
    with pytest.raises(Lcus2Error, match="ttyUSB0"):
        resolve_port(None, ports=ports, identify=lambda device, baud: False)


def test_status_reply_picks_the_lcus_among_ch340s():
    ports = [
        SerialPort("/dev/ttyUSB2", vid=0x1A86),
        SerialPort("/dev/ttyUSB3", vid=0x1A86),
    ]
    chosen = resolve_port(
        None,
        ports=ports,
        identify=lambda device, baud: device == "/dev/ttyUSB3",
    )
    assert chosen == "/dev/ttyUSB3"


def test_two_boards_that_answer_still_need_a_path():
    ports = [
        SerialPort("/dev/ttyUSB2", vid=0x1A86),
        SerialPort("/dev/ttyUSB3", vid=0x1A86),
    ]
    with pytest.raises(Lcus2Error, match="serial_path"):
        resolve_port(None, ports=ports, identify=lambda device, baud: True)


def test_macos_does_not_probe_multiple_ch340s(monkeypatch):
    monkeypatch.setattr("src.lcus2.ports.sys.platform", "darwin")

    def fail(device, baud):
        raise AssertionError(device)

    monkeypatch.setattr("src.lcus2.ports._answers_status", fail)
    ports = [
        SerialPort("/dev/ttyUSB2", vid=0x1A86),
        SerialPort("/dev/ttyUSB3", vid=0x1A86),
    ]
    with pytest.raises(Lcus2Error, match="Multiple CH340"):
        resolve_port(None, ports=ports)


def test_linux_probe_accepts_the_port_that_answers(monkeypatch):
    monkeypatch.setattr("src.lcus2.ports.sys.platform", "linux")
    monkeypatch.setattr("src.lcus2.ports._IDENTIFY_TIMEOUT", 0.01)
    from tests.fake_serial import FakeSerial

    def open_one(path, baud):
        port = FakeSerial(path, baud)
        if path != "/dev/ttyUSB3":
            port.replies = {}
        return port

    monkeypatch.setattr("src.lcus2.bus.open_serial", open_one)
    ports = [
        SerialPort("/dev/ttyUSB2", vid=0x1A86),
        SerialPort("/dev/ttyUSB3", vid=0x1A86),
    ]
    assert resolve_port(None, ports=ports) == "/dev/ttyUSB3"


def test_symlink_and_device_node_canonicalize(tmp_path):
    device = tmp_path / "ttyUSB0"
    device.write_text("")
    link = tmp_path / "by-id"
    link.symlink_to(device)
    assert canonical_device(str(link)) == canonical_device(str(device))
    assert canonical_device(str(link)) == os.path.realpath(device)
