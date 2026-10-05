import pytest

from src.lcus2.bus import reset_buses_for_tests
from tests.fake_serial import FakeSerial


@pytest.fixture(autouse=True)
def fake_serial_port(monkeypatch):
    FakeSerial.reset()
    reset_buses_for_tests()
    monkeypatch.setattr("src.lcus2.bus.open_serial", lambda path, baud: FakeSerial(path, baud))
    yield
    reset_buses_for_tests()
    FakeSerial.reset()
