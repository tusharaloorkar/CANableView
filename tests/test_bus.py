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
