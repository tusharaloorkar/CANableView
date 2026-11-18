from unittest.mock import Mock

import can
import pytest

from canableview.bus import BusConfig, BusManager


def test_virtual_roundtrip(qtbot):
    a, b = BusManager(), BusManager()
    got = []
    b.add_listener(got.append)
    a.open(BusConfig("virtual", "t1")); b.open(BusConfig("virtual", "t1"))
    assert a.send(can.Message(arbitration_id=0x123, data=b"\x01\x02"))
    qtbot.waitUntil(lambda: len(got) == 1, timeout=2000)
    assert got[0].arbitration_id == 0x123 and got[0].is_rx
    a.close(); b.close()


def test_send_echoes_tx_to_own_listeners(qtbot):
    a = BusManager(); seen = []
    a.add_listener(seen.append); a.open(BusConfig("virtual", "t2"))
    a.send(can.Message(arbitration_id=0x200, data=b"\x01"))
    assert len(seen) == 1 and seen[0].is_rx is False
    a.close()


def test_open_bad_port_emits_error(qtbot):
    m = BusManager()
    with qtbot.waitSignal(m.error, timeout=3000):
        m.open(BusConfig("slcan", "COM_DOES_NOT_EXIST"))
    assert not m.is_open


def test_send_when_closed_returns_false():
    assert BusManager().send(can.Message(arbitration_id=1)) is False


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # Notifier re-raises in its thread
def test_reader_failure_emits_error_and_disconnected(qtbot, monkeypatch):
    m = BusManager(); m.open(BusConfig("virtual", "t3"))
    monkeypatch.setattr(m._bus, "recv", Mock(side_effect=can.CanOperationError("unplugged")))
    with qtbot.waitSignals([m.error, m.disconnected], timeout=3000):
        pass
    assert not m.is_open


def test_send_periodic_echoes(qtbot):
    m = BusManager(); seen = []
    m.add_listener(seen.append); m.open(BusConfig("virtual", "t4"))
    task = m.send_periodic(can.Message(arbitration_id=0x300, data=b"\x01"), 0.02)
    qtbot.waitUntil(lambda: len(seen) >= 2, timeout=2000)
    task.stop()
    assert all(s.is_rx is False for s in seen)
    m.close()


def test_close_does_not_block_gui(qtbot):
    import time
    m = BusManager(); m.open(BusConfig("virtual", "t5"))
    t = time.perf_counter(); m.close()
    assert time.perf_counter() - t < 0.3


def _fake_gs_usb(monkeypatch, qtbot):
    real = can.Bus
    monkeypatch.setattr("canableview.bus.can.Bus", lambda **kw: real(interface="virtual", channel="gs", receive_own_messages=False))
    m = BusManager(); seen = []
    m.add_listener(seen.append); m.open(BusConfig("gs_usb", "0"))
    assert m.is_open
    return m, seen


def test_gs_usb_trusts_device_echo(monkeypatch, qtbot):
    m, seen = _fake_gs_usb(monkeypatch, qtbot)
    assert m.send(can.Message(arbitration_id=0x200, data=b"\x01"))
    task = m.send_periodic(can.Message(arbitration_id=0x300, data=b"\x01"), 0.01)
    qtbot.wait(100)
    task.stop()
    m.close()
    assert seen == []  # candleLight echoes TX itself (is_rx=False); a software echo would duplicate it


def test_gs_usb_restamps_with_host_clock(monkeypatch, qtbot):
    import time
    m, seen = _fake_gs_usb(monkeypatch, qtbot)
    m._dispatch(can.Message(arbitration_id=1, timestamp=5.0))  # device µs counter
    m.close()
    assert abs(seen[0].timestamp - time.time()) < 1


def test_send_survives_close_between_check_and_use(qtbot):
    class Racy(BusManager):
        reads = 0

        @property
        def _bus(self):
            Racy.reads += 1
            return self.__dict__.get("_b") if Racy.reads == 1 else None  # close() lands after the None check

        @_bus.setter
        def _bus(self, v):
            self.__dict__["_b"] = v
    m = Racy()
    m._bus = Mock()
    Racy.reads = 0
    assert m.send(can.Message(arbitration_id=1)) is True
    Racy.reads = 0
    m.send_periodic(can.Message(arbitration_id=1), 0.1)
