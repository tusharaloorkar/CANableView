from unittest.mock import Mock

import pytest

from canableview.transmit import TransmitWindow, TxRow, parse_hex


def _w(qtbot, is_open=True):
    bus = Mock(is_open=is_open)
    w = TransmitWindow(bus)
    qtbot.addWidget(w)
    return bus, w


def test_parse_hex_ok():
    assert parse_hex("01 02 0a", fd=False) == b"\x01\x02\x0a"
    assert parse_hex("01020A", fd=False) == b"\x01\x02\x0a"


@pytest.mark.parametrize("bad", ["zz", "123", "00 " * 9])
def test_parse_hex_rejects(bad):
    with pytest.raises(ValueError):
        parse_hex(bad, fd=False)


def test_parse_hex_fd_len():
    with pytest.raises(ValueError):
        parse_hex("00" * 9, fd=True)
    assert len(parse_hex("00" * 12, fd=True)) == 12


def test_send_requires_arm(qtbot):
    bus, w = _w(qtbot)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None))
    with qtbot.waitSignal(w.status) as sig:
        assert w.send_row(0) is False
    assert sig.args == ["Arm transmit first"]
    bus.send.assert_not_called()


def test_send_when_disconnected(qtbot):
    bus, w = _w(qtbot, is_open=False)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None))
    w.arm(True)
    with qtbot.waitSignal(w.status) as sig:
        assert w.send_row(0) is False
    assert sig.args == ["Not connected"]


def test_send_builds_message(qtbot):
    bus, w = _w(qtbot)
    bus.send.return_value = True
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None))
    w.arm(True)
    assert w.send_row(0) is True
    m = bus.send.call_args.args[0]
    assert (m.arbitration_id, m.is_extended_id, m.is_fd, m.data) == (0x200, False, False, b"\x01")


@pytest.mark.parametrize("row", [
    TxRow(0x800, False, False, False, b"", None),
    TxRow(0x20000000, True, False, False, b"", None),
    TxRow(0x1, False, False, True, b"", None),  # brs without fd
])
def test_invalid_row_not_sent(qtbot, row):
    bus, w = _w(qtbot)
    w.add_row(row)
    w.arm(True)
    with qtbot.waitSignal(w.status):
        assert w.send_row(0) is False
        assert w.start_cyclic(0) is False
    bus.send.assert_not_called()
    bus.send_periodic.assert_not_called()


def test_extended_id_ok(qtbot):
    bus, w = _w(qtbot)
    w.add_row(TxRow(0x1FFFFFFF, True, False, False, b"", None))
    w.arm(True)
    w.send_row(0)
    assert bus.send.call_args.args[0].is_extended_id is True


def test_stop_all_stops_tasks_and_disarms(qtbot):
    task = Mock()
    bus, w = _w(qtbot)
    bus.send_periodic.return_value = task
    w.add_row(TxRow(0x200, False, False, False, b"\x01", 100))
    w.arm(True)
    assert w.start_cyclic(0)
    with qtbot.waitSignal(w.stopped_all):
        w.stop_all()
    task.stop.assert_called_once()
    assert w.armed is False
    assert w.stop_btn.isEnabled()


def test_disarm_stops_cyclic(qtbot):
    task = Mock()
    bus, w = _w(qtbot)
    bus.send_periodic.return_value = task
    w.add_row(TxRow(0x200, False, False, False, b"\x01", 100))
    w.arm(True)
    w.start_cyclic(0)
    w.arm(False)
    task.stop.assert_called_once()


def test_cyclic_needs_arm_and_period(qtbot):
    bus, w = _w(qtbot)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", 100))
    w.add_row(TxRow(0x201, False, False, False, b"\x01", None))
    assert w.start_cyclic(0) is False
    w.arm(True)
    assert w.start_cyclic(1) is False
    bus.send_periodic.assert_not_called()


def test_cyclic_bus_closed_returns_false(qtbot):
    bus, w = _w(qtbot)
    bus.send_periodic.return_value = None
    w.add_row(TxRow(0x200, False, False, False, b"\x01", 100))
    w.arm(True)
    with qtbot.waitSignal(w.status) as sig:
        assert w.start_cyclic(0) is False
    assert sig.args == ["Not connected"]


def test_title_shows_armed(qtbot):
    _, w = _w(qtbot)
    assert w.windowTitle() == "Transmit"
    w.arm(True)
    assert w.windowTitle() == "Transmit \u2014 armed"
    w.arm(False)
    assert w.windowTitle() == "Transmit"


def test_edit_data_cell_valid_and_invalid(qtbot):
    _, w = _w(qtbot)
    w.add_row(TxRow(0x200, False, False, False, b"\x01", None))
    w.table.item(0, 4).setText("AA BB")
    assert w.rows[0].data == b"\xaa\xbb"
    with qtbot.waitSignal(w.status):
        w.table.item(0, 4).setText("zz")
    assert w.rows[0].data == b"\xaa\xbb"
    assert w.table.item(0, 4).text() == "AA BB"
