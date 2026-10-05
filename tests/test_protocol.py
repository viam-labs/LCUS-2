import pytest

from src.lcus2.protocol import OP_OFF, OP_ON, OP_QUERY, frame, parse_status


def test_documented_on_off_frames():
    assert frame(1, OP_ON) == bytes.fromhex("A0 01 01 A2")
    assert frame(1, OP_OFF) == bytes.fromhex("A0 01 00 A1")
    assert frame(2, OP_ON) == bytes.fromhex("A0 02 01 A3")
    assert frame(2, OP_OFF) == bytes.fromhex("A0 02 00 A2")


def test_query_frame_checksum():
    assert frame(1, OP_QUERY) == bytes.fromhex("A0 01 02 A3")
    assert frame(2, OP_QUERY) == bytes.fromhex("A0 02 02 A4")


def test_frame_rejects_unknown_channel():
    with pytest.raises(ValueError):
        frame(3, OP_ON)


@pytest.mark.parametrize(
    "payload",
    [
        b"CH1: ON\r\nCH2: OFF\r\n",
        b"CH1: ON \r\nCH2: OFF\r\n",
        b"CH1:ON\r\nCH2:OFF\r\n",
        b"ch1: on\r\nch2: off\r\n",
    ],
)
def test_parse_status_accepts_documented_layouts(payload):
    assert parse_status(payload) == {1: True, 2: False}


def test_parse_status_ignores_noise():
    assert parse_status(b"\x00\xffready CH2: ON\r\n") == {2: True}
